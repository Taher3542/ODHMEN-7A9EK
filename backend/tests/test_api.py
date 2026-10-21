from io import BytesIO
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw

from app import main


@pytest.fixture()
def client(tmp_path, monkeypatch):
    data = tmp_path / "data"
    uploads = data / "uploads"
    reports = data / "reports"
    monkeypatch.setattr(main, "DATA_DIR", data)
    monkeypatch.setattr(main, "UPLOAD_DIR", uploads)
    monkeypatch.setattr(main, "REPORT_DIR", reports)
    monkeypatch.setattr(main, "DB_PATH", data / "test.db")
    data.mkdir(parents=True, exist_ok=True)
    uploads.mkdir(parents=True, exist_ok=True)
    reports.mkdir(parents=True, exist_ok=True)
    with TestClient(main.app) as test_client:
        yield test_client


def make_png(change=False):
    image = Image.new("RGB", (320, 220), (90, 105, 120))
    draw = ImageDraw.Draw(image)
    draw.rectangle((35, 55, 285, 160), outline="white", width=4)
    draw.ellipse((55, 145, 110, 200), fill="black")
    draw.ellipse((215, 145, 270, 200), fill="black")
    if change:
        draw.rectangle((145, 70, 205, 120), fill="red")
    output = BytesIO()
    image.save(output, format="PNG")
    return output.getvalue()


def image_uploads(change=False):
    result = {}
    for index, angle in enumerate(main.ANGLES):
        result[angle] = (f"{angle}.png", make_png(change=change and index == 0), "image/png")
    return result


def test_health_shows_explicit_local_hedera_mode(client):
    response = client.get("/api/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"
    assert response.json()["hedera_mode"] == "local-simulation"


def test_create_vehicle_and_duplicate_registration(client):
    payload = {"make": "Toyota", "model": "Yaris", "registration": "TEST 123", "year": 2022, "mileage": 25000, "fuel_level": 80}
    assert client.post("/api/vehicles", json=payload).status_code == 200
    duplicate = client.post("/api/vehicles", json=payload)
    assert duplicate.status_code == 409


def test_initial_inspection_creates_vehicle_with_characteristics(client):
    fields = {
        "make": "Toyota", "model": "Yaris", "registration": "TEST 456", "year": "2023",
        "mileage": "25100", "fuel_level": "75",
    }
    response = client.post("/api/inspections/before", data=fields, files=image_uploads())
    assert response.status_code == 200, response.text
    before_data = response.json()
    inspection_id = before_data["inspection_id"]

    inspection = client.get(f"/api/inspections/{inspection_id}")
    assert inspection.status_code == 200
    assert inspection.json()["make"] == "Toyota"
    assert inspection.json()["model"] == "Yaris"
    assert inspection.json()["registration"] == "TEST456"
    assert inspection.json()["year"] == 2023

    anchored_event = next(
        event for event in client.get("/api/events").json()
        if event["reference_id"] == inspection_id
    )
    assert len(anchored_event["payload_json"].encode("utf-8")) <= 1024
    assert len(json.loads(anchored_event["payload_json"])["photo_hashes"]) == 8

    dashboard = client.get("/api/dashboard").json()
    assert dashboard["inspections_total"] == 1
    assert dashboard["inspections_before"] == 1
    assert dashboard["inspections_after"] == 0
    assert dashboard["rentals_active"] == 1

    after_fields = {**fields, "mileage": "25200", "fuel_level": "70"}
    returned = client.post(
        f"/api/rentals/{before_data['rental_id']}/after-inspection",
        data=after_fields,
        files=image_uploads(change=True),
    )
    assert returned.status_code == 200, returned.text

    next_inspection = client.post("/api/inspections/before", data=fields, files=image_uploads())
    assert next_inspection.status_code == 200, next_inspection.text

    dashboard = client.get("/api/dashboard").json()
    assert dashboard["inspections_total"] == 3
    assert dashboard["inspections_before"] == 2
    assert dashboard["inspections_after"] == 1
    assert dashboard["rentals_active"] == 1


def test_complete_rental_lifecycle_and_hash_verification(client):
    vehicle = client.post("/api/vehicles", json={
        "make": "Toyota", "model": "Yaris", "registration": "LIFE-123", "year": 2022,
        "mileage": 25000, "fuel_level": 80
    }).json()
    common_fields = {"mileage": "25100", "fuel_level": "75", "engine_info": "OK", "oil_info": "OK",
                     "tire_info": "OK", "dashboard_info": "Aucun voyant", "interior_info": "Propre",
                     "exterior_info": "Contrôlé", "notes": "Test automatique"}
    before = client.post(f"/api/vehicles/{vehicle['id']}/before-inspection", data=common_fields, files=image_uploads())
    assert before.status_code == 200, before.text
    before_data = before.json()
    assert before_data["photo_count"] == 8
    assert before_data["vehicle_status"] == "En location"
    assert before_data["hedera"]["status"] == "simulation"

    # The same vehicle cannot start a second rental before returning the current one.
    second_before = client.post(f"/api/vehicles/{vehicle['id']}/before-inspection", data=common_fields, files=image_uploads())
    assert second_before.status_code == 409

    after_fields = {**common_fields, "mileage": "25200", "fuel_level": "70"}
    after = client.post(f"/api/rentals/{before_data['rental_id']}/after-inspection", data=after_fields, files=image_uploads(change=True))
    assert after.status_code == 200, after.text
    after_data = after.json()
    assert after_data["vehicle_status"] == "Retournée"
    assert after_data["assessment"]["id"]
    assert len(after_data["assessment"]["summary"]["differences"]) == 8

    verification = client.get(f"/api/verify/inspection/{before_data['inspection_id']}")
    assert verification.status_code == 200
    assert verification.json()["hash_matches"] is True
    assert client.get(f"/api/files/{before_data['inspection_id']}?kind=report").status_code == 200
    assert len(client.get("/api/inspections").json()) == 2
