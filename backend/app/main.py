from __future__ import annotations
import hashlib
from contextlib import asynccontextmanager
import json
import os
import re
import shutil
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import cv2
import numpy as np
from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel, Field
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, Image as RLImage, PageBreak

from .hedera_service import submit_event, hedera_configured

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
DATA_DIR = Path(os.getenv("DATA_DIR", str(ROOT / "data"))).resolve()
UPLOAD_DIR = DATA_DIR / "uploads"
REPORT_DIR = DATA_DIR / "reports"
DB_PATH = DATA_DIR / "odhmen.db"
MAX_UPLOAD_MB = int(os.getenv("MAX_UPLOAD_MB", "12"))
MAX_UPLOAD_BYTES = MAX_UPLOAD_MB * 1024 * 1024
ALLOWED_TYPES = {"image/jpeg", "image/png", "image/webp"}
ANGLES = ["avant", "arriere", "cote_gauche", "cote_droit", "avant_gauche", "avant_droit", "arriere_gauche", "arriere_droit"]
ANGLE_LABELS = {
    "avant": "Avant", "arriere": "Arrière", "cote_gauche": "Côté gauche", "cote_droit": "Côté droit",
    "avant_gauche": "Avant gauche", "avant_droit": "Avant droit", "arriere_gauche": "Arrière gauche", "arriere_droit": "Arrière droit"
}
for folder in (DATA_DIR, UPLOAD_DIR, REPORT_DIR):
    folder.mkdir(parents=True, exist_ok=True)

@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    yield


app = FastAPI(title="ODHMEN 7A9EK API", version="1.0.0", description="Inspection automobile avec rapports et ancrage HCS optionnel", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[x.strip() for x in os.getenv("CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173").split(",")],
    allow_credentials=False, allow_methods=["GET", "POST", "OPTIONS"], allow_headers=["*"]
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    con = sqlite3.connect(DB_PATH, timeout=15)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")
    return con


def init_db() -> None:
    with connect() as con:
        con.executescript('''
        CREATE TABLE IF NOT EXISTS vehicles (
          id TEXT PRIMARY KEY, make TEXT NOT NULL, model TEXT NOT NULL, registration TEXT NOT NULL UNIQUE,
          year INTEGER, mileage INTEGER NOT NULL DEFAULT 0, fuel_level REAL NOT NULL DEFAULT 0,
          engine_info TEXT DEFAULT '', oil_info TEXT DEFAULT '', tire_info TEXT DEFAULT '', dashboard_info TEXT DEFAULT '',
          interior_info TEXT DEFAULT '', exterior_info TEXT DEFAULT '', notes TEXT DEFAULT '',
          status TEXT NOT NULL DEFAULT 'Disponible', created_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS rentals (
          id TEXT PRIMARY KEY, vehicle_id TEXT NOT NULL REFERENCES vehicles(id), status TEXT NOT NULL,
          started_at TEXT NOT NULL, returned_at TEXT, start_mileage INTEGER, return_mileage INTEGER
        );
        CREATE TABLE IF NOT EXISTS inspections (
          id TEXT PRIMARY KEY, vehicle_id TEXT NOT NULL REFERENCES vehicles(id), rental_id TEXT NOT NULL REFERENCES rentals(id),
          kind TEXT NOT NULL CHECK(kind IN ('INSPECTION_AVANT','INSPECTION_APRES')), created_at TEXT NOT NULL,
          mileage INTEGER NOT NULL, fuel_level REAL NOT NULL, engine_info TEXT DEFAULT '', oil_info TEXT DEFAULT '',
          tire_info TEXT DEFAULT '', dashboard_info TEXT DEFAULT '', interior_info TEXT DEFAULT '', exterior_info TEXT DEFAULT '',
          notes TEXT DEFAULT '', report_path TEXT, report_hash TEXT, hedera_status TEXT NOT NULL DEFAULT 'pending',
          hedera_tx TEXT, consensus_timestamp TEXT, hedera_message TEXT
        );
        CREATE TABLE IF NOT EXISTS photos (
          id TEXT PRIMARY KEY, inspection_id TEXT NOT NULL REFERENCES inspections(id), angle TEXT NOT NULL,
          file_path TEXT NOT NULL, sha256 TEXT NOT NULL, mime_type TEXT NOT NULL, size_bytes INTEGER NOT NULL,
          UNIQUE(inspection_id, angle)
        );
        CREATE TABLE IF NOT EXISTS assessments (
          id TEXT PRIMARY KEY, vehicle_id TEXT NOT NULL REFERENCES vehicles(id), rental_id TEXT NOT NULL REFERENCES rentals(id),
          before_inspection_id TEXT NOT NULL REFERENCES inspections(id), after_inspection_id TEXT NOT NULL REFERENCES inspections(id),
          created_at TEXT NOT NULL, summary_json TEXT NOT NULL, report_path TEXT, report_hash TEXT,
          hedera_status TEXT NOT NULL DEFAULT 'pending', hedera_tx TEXT, consensus_timestamp TEXT, hedera_message TEXT
        );
        CREATE TABLE IF NOT EXISTS hedera_events (
          id TEXT PRIMARY KEY, event_type TEXT NOT NULL, reference_id TEXT NOT NULL, payload_json TEXT NOT NULL,
          status TEXT NOT NULL, transaction_id TEXT, consensus_timestamp TEXT, message TEXT, created_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_vehicles_registration ON vehicles(registration);
        CREATE INDEX IF NOT EXISTS idx_inspections_vehicle ON inspections(vehicle_id, created_at);
        CREATE INDEX IF NOT EXISTS idx_rentals_vehicle ON rentals(vehicle_id, started_at);
        ''')


class VehicleCreate(BaseModel):
    make: str = Field(min_length=1, max_length=60)
    model: str = Field(min_length=1, max_length=80)
    registration: str = Field(min_length=2, max_length=20)
    year: int | None = Field(default=None, ge=1950, le=2100)
    mileage: int = Field(ge=0)
    fuel_level: float = Field(ge=0, le=100)
    engine_info: str = ""
    oil_info: str = ""
    tire_info: str = ""
    dashboard_info: str = ""
    interior_info: str = ""
    exterior_info: str = ""
    notes: str = ""


def rowdict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    return dict(row) if row else None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def event_anchor(event_type: str, reference_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    body = {"schema_version": 1, "event_type": event_type, "reference_id": reference_id, "app_submitted_at": now_iso(), **payload}
    result = submit_event(body)
    event_id = str(uuid.uuid4())
    with connect() as con:
        con.execute("INSERT INTO hedera_events(id,event_type,reference_id,payload_json,status,transaction_id,consensus_timestamp,message,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (event_id, event_type, reference_id, json.dumps(body, ensure_ascii=False), result["status"], result.get("transaction_id"), result.get("consensus_timestamp"), result.get("message"), now_iso()))
    return {"event_id": event_id, **result}


def safe_path(path_value: str | Path) -> Path:
    path = Path(path_value).resolve()
    if UPLOAD_DIR not in path.parents and REPORT_DIR not in path.parents:
        raise HTTPException(status_code=403, detail="Chemin de fichier non autorisé.")
    if not path.exists() or not path.is_file():
        raise HTTPException(status_code=404, detail="Fichier introuvable.")
    return path


def make_pdf(title: str, vehicle: dict[str, Any], details: dict[str, Any], photos: list[dict[str, Any]], output: Path,
             extra: dict[str, Any] | None = None) -> str:
    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(name="BrandTitle", parent=styles["Title"], textColor=colors.HexColor("#d93636"), fontSize=22, leading=26, spaceAfter=10))
    styles.add(ParagraphStyle(name="SectionRed", parent=styles["Heading2"], textColor=colors.HexColor("#c92f38"), spaceBefore=12, spaceAfter=6))
    doc = SimpleDocTemplate(str(output), pagesize=A4, rightMargin=1.6*cm, leftMargin=1.6*cm, topMargin=1.5*cm, bottomMargin=1.5*cm)
    story: list[Any] = [Paragraph("ODHMEN 7A9EK", styles["BrandTitle"]), Paragraph(title, styles["Heading1"]), Spacer(1, 7)]
    info = [
        ["Véhicule", f'{vehicle.get("make", "")} {vehicle.get("model", "")}'],
        ["Immatriculation", vehicle.get("registration", "")], ["Année", str(vehicle.get("year") or "—")],
        ["Identifiant véhicule", vehicle.get("id", "")], ["Date", details.get("created_at", now_iso())],
        ["Kilométrage", str(details.get("mileage", "—")) + " km"], ["Carburant", str(details.get("fuel_level", "—")) + "%"],
    ]
    table = Table(info, colWidths=[4.3*cm, 12*cm])
    table.setStyle(TableStyle([("BACKGROUND", (0,0),(0,-1), colors.HexColor("#f2e6e6")), ("GRID",(0,0),(-1,-1),0.35,colors.HexColor("#dddddd")), ("VALIGN",(0,0),(-1,-1),"TOP"), ("PADDING",(0,0),(-1,-1),6)]))
    story += [table, Paragraph("Contrôles et observations", styles["SectionRed"])]
    labels = [("Moteur", "engine_info"), ("Huile", "oil_info"), ("Pneus", "tire_info"), ("Voyants", "dashboard_info"), ("Intérieur", "interior_info"), ("Extérieur", "exterior_info"), ("Notes", "notes")]
    for label, key in labels:
        value = str(details.get(key) or "Non renseigné").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        story.append(Paragraph(f"<b>{label} :</b> {value}", styles["BodyText"]))
        story.append(Spacer(1, 4))
    story.append(Paragraph("Photos de contrôle (8 angles)", styles["SectionRed"]))
    for photo in sorted(photos, key=lambda x: ANGLES.index(x["angle"]) if x["angle"] in ANGLES else 99):
        p = Path(photo["file_path"])
        if p.exists():
            story.append(Paragraph(f"<b>{ANGLE_LABELS.get(photo['angle'], photo['angle'])}</b> — SHA-256 : {photo['sha256']}", styles["BodyText"]))
            try:
                im = RLImage(str(p), width=8.5*cm, height=5.2*cm, kind="proportional")
                story.append(im)
                story.append(Spacer(1, 7))
            except Exception:
                pass
    if extra:
        story.append(PageBreak())
        story.append(Paragraph("Bilan comparatif", styles["SectionRed"]))
        story.append(Paragraph(str(extra.get("conclusion", "Analyse à vérifier")), styles["Heading2"]))
        for item in extra.get("differences", []):
            line = f"{item.get('angle_label', item.get('angle',''))} : différence estimée {item.get('difference_percent', '—')}% — {item.get('interpretation','') }"
            story.append(Paragraph(line.replace("&", "&amp;"), styles["BodyText"]))
            story.append(Spacer(1, 5))
        story.append(Paragraph("Cette comparaison visuelle est une aide au contrôle, pas une preuve définitive de dommage. L'inspecteur doit confirmer les observations.", styles["Italic"]))
    doc.build(story)
    return sha256_file(output)


async def save_photo(upload: UploadFile, folder: Path, angle: str) -> dict[str, Any]:
    if upload.content_type not in ALLOWED_TYPES:
        raise HTTPException(status_code=415, detail=f"Format non autorisé pour {ANGLE_LABELS[angle]}. Utilisez JPG, PNG ou WEBP.")
    raw = await upload.read(MAX_UPLOAD_BYTES + 1)
    if not raw:
        raise HTTPException(status_code=400, detail=f"Photo vide : {ANGLE_LABELS[angle]}.")
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail=f"La photo {ANGLE_LABELS[angle]} dépasse {MAX_UPLOAD_MB} Mo.")
    # Decode the image instead of trusting only the extension or MIME header.
    arr = np.frombuffer(raw, dtype=np.uint8)
    image = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if image is None:
        raise HTTPException(status_code=400, detail=f"Fichier image invalide : {ANGLE_LABELS[angle]}.")
    folder.mkdir(parents=True, exist_ok=True)
    ext = ".jpg" if upload.content_type == "image/jpeg" else ".png" if upload.content_type == "image/png" else ".webp"
    path = folder / f"{angle}{ext}"
    # Use exclusive creation so validated originals cannot be silently overwritten.
    with path.open("xb") as f:
        f.write(raw)
    return {"id": str(uuid.uuid4()), "angle": angle, "file_path": str(path), "sha256": hashlib.sha256(raw).hexdigest(), "mime_type": upload.content_type, "size_bytes": len(raw)}


def insert_photos(con: sqlite3.Connection, inspection_id: str, photos: list[dict[str, Any]]) -> None:
    for p in photos:
        con.execute("INSERT INTO photos(id,inspection_id,angle,file_path,sha256,mime_type,size_bytes) VALUES(?,?,?,?,?,?,?)",
                    (p["id"], inspection_id, p["angle"], p["file_path"], p["sha256"], p["mime_type"], p["size_bytes"]))


def get_inspection(con: sqlite3.Connection, inspection_id: str) -> dict[str, Any] | None:
    row = con.execute("SELECT * FROM inspections WHERE id=?", (inspection_id,)).fetchone()
    if not row: return None
    data = dict(row)
    data["photos"] = [dict(p) for p in con.execute("SELECT * FROM photos WHERE inspection_id=? ORDER BY angle", (inspection_id,)).fetchall()]
    return data


def image_diff(before_path: Path, after_path: Path) -> tuple[float, str]:
    a = cv2.imread(str(before_path)); b = cv2.imread(str(after_path))
    if a is None or b is None:
        return 100.0, "Impossible de lire l'une des images"
    # A simple technical diff score, not a trained damage detector.
    target = (640, 420)
    a = cv2.resize(a, target); b = cv2.resize(b, target)
    a_gray = cv2.cvtColor(a, cv2.COLOR_BGR2GRAY); b_gray = cv2.cvtColor(b, cv2.COLOR_BGR2GRAY)
    # Blur reduces tiny compression/noise effects without claiming geometric registration.
    a_gray = cv2.GaussianBlur(a_gray, (5, 5), 0); b_gray = cv2.GaussianBlur(b_gray, (5, 5), 0)
    diff = cv2.absdiff(a_gray, b_gray)
    _, mask = cv2.threshold(diff, 28, 255, cv2.THRESH_BINARY)
    changed = float(np.count_nonzero(mask)) / float(mask.size) * 100.0
    interpretation = "Différence visuelle faible" if changed < 8 else "Différence visuelle à examiner" if changed < 22 else "Différence visuelle importante à vérifier"
    return round(changed, 2), interpretation


def get_vehicle_or_404(con: sqlite3.Connection, vehicle_id: str) -> dict[str, Any]:
    vehicle = rowdict(con.execute("SELECT * FROM vehicles WHERE id=?", (vehicle_id,)).fetchone())
    if not vehicle: raise HTTPException(status_code=404, detail="Véhicule introuvable.")
    return vehicle


@app.get("/api/health")
def health() -> dict[str, Any]:
    return {"status": "ok", "app": "ODHMEN 7A9EK", "hedera_configured": hedera_configured(), "hedera_mode": "testnet-ready" if hedera_configured() else "local-simulation", "angles": ANGLES}


@app.get("/api/dashboard")
def dashboard() -> dict[str, Any]:
    with connect() as con:
        total = con.execute("SELECT COUNT(*) FROM vehicles").fetchone()[0]
        rented = con.execute("SELECT COUNT(*) FROM vehicles WHERE status='En location'").fetchone()[0]
        returned = con.execute("SELECT COUNT(*) FROM vehicles WHERE status='Retournée'").fetchone()[0]
        available = con.execute("SELECT COUNT(*) FROM vehicles WHERE status='Disponible'").fetchone()[0]
        inspections_total = con.execute("SELECT COUNT(*) FROM inspections").fetchone()[0]
        inspections_before = con.execute("SELECT COUNT(*) FROM inspections WHERE kind='INSPECTION_AVANT'").fetchone()[0]
        inspections_after = con.execute("SELECT COUNT(*) FROM inspections WHERE kind='INSPECTION_APRES'").fetchone()[0]
        rentals_active = con.execute("SELECT COUNT(*) FROM rentals WHERE status='active'").fetchone()[0]
        events = [dict(x) for x in con.execute("SELECT * FROM hedera_events ORDER BY created_at DESC LIMIT 8").fetchall()]
        inspections = [dict(x) for x in con.execute("SELECT i.id,i.kind,i.created_at,i.hedera_status,v.registration,v.make,v.model FROM inspections i JOIN vehicles v ON v.id=i.vehicle_id ORDER BY i.created_at DESC LIMIT 6").fetchall()]
        return {"vehicles_total": total, "vehicles_rented": rented, "vehicles_returned": returned, "vehicles_available": available,
                "inspections_total": inspections_total, "inspections_before": inspections_before, "inspections_after": inspections_after,
                "rentals_active": rentals_active, "recent_events": events, "recent_inspections": inspections,
                "hedera_configured": hedera_configured()}


@app.get("/api/vehicles")
def list_vehicles(q: str = "") -> list[dict[str, Any]]:
    with connect() as con:
        term = f"%{q.strip()}%"
        rows = con.execute("SELECT * FROM vehicles WHERE registration LIKE ? OR make LIKE ? OR model LIKE ? ORDER BY created_at DESC", (term, term, term)).fetchall()
        return [dict(x) for x in rows]


@app.post("/api/vehicles")
def create_vehicle(item: VehicleCreate) -> dict[str, Any]:
    vehicle_id = str(uuid.uuid4())
    registration = re.sub(r"\s+", "", item.registration.upper())
    now = now_iso()
    try:
        with connect() as con:
            con.execute("""INSERT INTO vehicles(id,make,model,registration,year,mileage,fuel_level,engine_info,oil_info,tire_info,dashboard_info,interior_info,exterior_info,notes,status,created_at)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (vehicle_id,item.make.strip(),item.model.strip(),registration,item.year,item.mileage,item.fuel_level,item.engine_info,item.oil_info,item.tire_info,item.dashboard_info,item.interior_info,item.exterior_info,item.notes,"Disponible",now))
            return dict(con.execute("SELECT * FROM vehicles WHERE id=?", (vehicle_id,)).fetchone())
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=409, detail="Cette immatriculation existe déjà.")



@app.get("/api/rentals")
def list_rentals(status: str = "active") -> list[dict[str, Any]]:
    with connect() as con:
        if status not in ("active", "returned", "all"):
            raise HTTPException(status_code=400, detail="Statut invalide.")
        sql = "SELECT r.*,v.registration,v.make,v.model,v.status AS vehicle_status FROM rentals r JOIN vehicles v ON v.id=r.vehicle_id"
        params: tuple[Any, ...] = ()
        if status != "all":
            sql += " WHERE r.status=?"
            params = (status,)
        sql += " ORDER BY r.started_at DESC"
        return [dict(r) for r in con.execute(sql, params).fetchall()]


@app.get("/api/vehicles/{vehicle_id}")
def vehicle_detail(vehicle_id: str) -> dict[str, Any]:
    with connect() as con:
        vehicle = get_vehicle_or_404(con, vehicle_id)
        vehicle["history"] = [dict(r) for r in con.execute("""SELECT i.id,i.kind,i.created_at,i.mileage,i.fuel_level,i.report_hash,i.hedera_status,i.hedera_tx
            FROM inspections i WHERE i.vehicle_id=? ORDER BY i.created_at DESC""", (vehicle_id,)).fetchall()]
        vehicle["assessments"] = [dict(r) for r in con.execute("SELECT id,created_at,report_hash,hedera_status,hedera_tx FROM assessments WHERE vehicle_id=? ORDER BY created_at DESC", (vehicle_id,)).fetchall()]
        return vehicle


async def _create_inspection(vehicle_id: str, kind: str, mileage: int, fuel_level: float, engine_info: str, oil_info: str, tire_info: str,
    dashboard_info: str, interior_info: str, exterior_info: str, notes: str, uploads: dict[str, UploadFile],
    vehicle_details: dict[str, Any] | None = None) -> dict[str, Any]:
    if mileage < 0 or not 0 <= fuel_level <= 100:
        raise HTTPException(status_code=422, detail="Vérifiez le kilométrage et le carburant (0 à 100%).")
    if set(uploads.keys()) != set(ANGLES):
        raise HTTPException(status_code=422, detail="Exactement 8 photos obligatoires sont requises, une par angle.")
    inspection_id = str(uuid.uuid4())
    created = now_iso()
    photo_folder = UPLOAD_DIR / inspection_id
    photos: list[dict[str, Any]] = []
    try:
        for angle in ANGLES:
            photos.append(await save_photo(uploads[angle], photo_folder, angle))
        with connect() as con:
            if vehicle_details:
                existing_vehicle = con.execute("SELECT * FROM vehicles WHERE registration=?", (vehicle_details["registration"],)).fetchone()
                if existing_vehicle:
                    vehicle = dict(existing_vehicle)
                    if (vehicle["make"].casefold(), vehicle["model"].casefold()) != (
                        vehicle_details["make"].casefold(), vehicle_details["model"].casefold()
                    ):
                        raise HTTPException(status_code=409, detail="Cette immatriculation est déjà associée à une autre marque ou un autre modèle.")
                    vehicle_id = vehicle["id"]
                else:
                    vehicle_id = str(uuid.uuid4())
                    con.execute("""INSERT INTO vehicles(id,make,model,registration,year,mileage,fuel_level,status,created_at)
                        VALUES(?,?,?,?,?,?,?,'Disponible',?)""",
                        (vehicle_id, vehicle_details["make"], vehicle_details["model"], vehicle_details["registration"],
                         vehicle_details["year"], mileage, fuel_level, created))
            vehicle = get_vehicle_or_404(con, vehicle_id)
            active_rental = con.execute("SELECT * FROM rentals WHERE vehicle_id=? AND status='active' ORDER BY started_at DESC LIMIT 1", (vehicle_id,)).fetchone()
            if kind == "INSPECTION_AVANT":
                if vehicle["status"] == "En location" or active_rental:
                    raise HTTPException(status_code=409, detail="Ce véhicule possède déjà une location active.")
                rental_id = str(uuid.uuid4())
                con.execute("INSERT INTO rentals(id,vehicle_id,status,started_at,start_mileage) VALUES(?,?,?,?,?)", (rental_id,vehicle_id,"active",created,mileage))
            else:
                if vehicle["status"] != "En location" or not active_rental:
                    raise HTTPException(status_code=409, detail="Le véhicule n'est pas en location.")
                rental_id = active_rental["id"]
                before = con.execute("SELECT id FROM inspections WHERE rental_id=? AND kind='INSPECTION_AVANT'", (rental_id,)).fetchone()
                if not before:
                    raise HTTPException(status_code=409, detail="Inspection initiale introuvable.")
            con.execute("""INSERT INTO inspections(id,vehicle_id,rental_id,kind,created_at,mileage,fuel_level,engine_info,oil_info,tire_info,dashboard_info,interior_info,exterior_info,notes)
              VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (inspection_id,vehicle_id,rental_id,kind,created,mileage,fuel_level,engine_info,oil_info,tire_info,dashboard_info,interior_info,exterior_info,notes))
            insert_photos(con, inspection_id, photos)
            if kind == "INSPECTION_AVANT":
                con.execute("UPDATE vehicles SET status='En location', mileage=?,fuel_level=?,engine_info=?,oil_info=?,tire_info=?,dashboard_info=?,interior_info=?,exterior_info=?,notes=? WHERE id=?",(mileage,fuel_level,engine_info,oil_info,tire_info,dashboard_info,interior_info,exterior_info,notes,vehicle_id))
            else:
                con.execute("UPDATE rentals SET status='returned',returned_at=?,return_mileage=? WHERE id=?",(created,mileage,rental_id))
                con.execute("UPDATE vehicles SET status='Retournée',mileage=?,fuel_level=?,engine_info=?,oil_info=?,tire_info=?,dashboard_info=?,interior_info=?,exterior_info=?,notes=? WHERE id=?",(mileage,fuel_level,engine_info,oil_info,tire_info,dashboard_info,interior_info,exterior_info,notes,vehicle_id))
            vehicle = dict(con.execute("SELECT * FROM vehicles WHERE id=?", (vehicle_id,)).fetchone())
        report_path = REPORT_DIR / f"inspection_{inspection_id}.pdf"
        report_hash = make_pdf("Rapport avant location" if kind == "INSPECTION_AVANT" else "Rapport au retour", vehicle,
            {"created_at": created,"mileage":mileage,"fuel_level":fuel_level,"engine_info":engine_info,"oil_info":oil_info,"tire_info":tire_info,"dashboard_info":dashboard_info,"interior_info":interior_info,"exterior_info":exterior_info,"notes":notes}, photos, report_path)
        event = event_anchor(kind, inspection_id, {
            "vehicle_id": vehicle_id,
            "rental_id": rental_id,
            "report_sha256": report_hash,
            "photo_hashes": [p["sha256"] for p in photos],
        })
        with connect() as con:
            con.execute("UPDATE inspections SET report_path=?,report_hash=?,hedera_status=?,hedera_tx=?,consensus_timestamp=?,hedera_message=? WHERE id=?",
                (str(report_path),report_hash,event["status"],event.get("transaction_id"),event.get("consensus_timestamp"),event.get("message"),inspection_id))
        return {"inspection_id":inspection_id,"rental_id":rental_id,"kind":kind,"vehicle_status":"En location" if kind=="INSPECTION_AVANT" else "Retournée",
                "created_at":created,"photo_count":len(photos),"report_hash":report_hash,"hedera":event}
    except Exception:
        # Files are retained for forensic safety; clean only when no inspection has been recorded.
        with connect() as con:
            exists = con.execute("SELECT 1 FROM inspections WHERE id=?",(inspection_id,)).fetchone()
        if not exists and photo_folder.exists():
            shutil.rmtree(photo_folder, ignore_errors=True)
        raise


@app.post("/api/vehicles/{vehicle_id}/before-inspection")
async def before_inspection(
    vehicle_id: str,
    mileage: int = Form(...), fuel_level: float = Form(...), engine_info: str = Form(""), oil_info: str = Form(""),
    tire_info: str = Form(""), dashboard_info: str = Form(""), interior_info: str = Form(""), exterior_info: str = Form(""), notes: str = Form(""),
    avant: UploadFile = File(...), arriere: UploadFile = File(...), cote_gauche: UploadFile = File(...), cote_droit: UploadFile = File(...),
    avant_gauche: UploadFile = File(...), avant_droit: UploadFile = File(...), arriere_gauche: UploadFile = File(...), arriere_droit: UploadFile = File(...)
) -> dict[str, Any]:
    return await _create_inspection(vehicle_id,"INSPECTION_AVANT",mileage,fuel_level,engine_info,oil_info,tire_info,dashboard_info,interior_info,exterior_info,notes,
      {"avant":avant,"arriere":arriere,"cote_gauche":cote_gauche,"cote_droit":cote_droit,"avant_gauche":avant_gauche,"avant_droit":avant_droit,"arriere_gauche":arriere_gauche,"arriere_droit":arriere_droit})


@app.post("/api/inspections/before")
async def create_vehicle_inspection(
    make: str = Form(...), model: str = Form(...), registration: str = Form(...), year: int | None = Form(None),
    mileage: int = Form(...), fuel_level: float = Form(...), engine_info: str = Form(""), oil_info: str = Form(""),
    tire_info: str = Form(""), dashboard_info: str = Form(""), interior_info: str = Form(""), exterior_info: str = Form(""), notes: str = Form(""),
    avant: UploadFile = File(...), arriere: UploadFile = File(...), cote_gauche: UploadFile = File(...), cote_droit: UploadFile = File(...),
    avant_gauche: UploadFile = File(...), avant_droit: UploadFile = File(...), arriere_gauche: UploadFile = File(...), arriere_droit: UploadFile = File(...)
) -> dict[str, Any]:
    make = make.strip()
    model = model.strip()
    registration = re.sub(r"\s+", "", registration.upper())
    if not make or len(make) > 60 or not model or len(model) > 80 or len(registration) < 2 or len(registration) > 20:
        raise HTTPException(status_code=422, detail="Vérifiez la marque, le modèle et l’immatriculation du véhicule.")
    if year is not None and not 1950 <= year <= 2100:
        raise HTTPException(status_code=422, detail="L’année du véhicule doit être comprise entre 1950 et 2100.")
    return await _create_inspection("", "INSPECTION_AVANT", mileage, fuel_level, engine_info, oil_info, tire_info,
        dashboard_info, interior_info, exterior_info, notes,
        {"avant":avant,"arriere":arriere,"cote_gauche":cote_gauche,"cote_droit":cote_droit,"avant_gauche":avant_gauche,
         "avant_droit":avant_droit,"arriere_gauche":arriere_gauche,"arriere_droit":arriere_droit},
        {"make":make,"model":model,"registration":registration,"year":year})


@app.post("/api/rentals/{rental_id}/after-inspection")
async def after_inspection(
    rental_id: str,
    mileage: int = Form(...), fuel_level: float = Form(...), engine_info: str = Form(""), oil_info: str = Form(""),
    tire_info: str = Form(""), dashboard_info: str = Form(""), interior_info: str = Form(""), exterior_info: str = Form(""), notes: str = Form(""),
    avant: UploadFile = File(...), arriere: UploadFile = File(...), cote_gauche: UploadFile = File(...), cote_droit: UploadFile = File(...),
    avant_gauche: UploadFile = File(...), avant_droit: UploadFile = File(...), arriere_gauche: UploadFile = File(...), arriere_droit: UploadFile = File(...)
) -> dict[str, Any]:
    with connect() as con:
        rental = rowdict(con.execute("SELECT * FROM rentals WHERE id=?", (rental_id,)).fetchone())
        if not rental: raise HTTPException(status_code=404, detail="Location introuvable.")
        if rental["status"] != "active": raise HTTPException(status_code=409, detail="Cette location est déjà clôturée.")
        vehicle_id = rental["vehicle_id"]
    result = await _create_inspection(vehicle_id,"INSPECTION_APRES",mileage,fuel_level,engine_info,oil_info,tire_info,dashboard_info,interior_info,exterior_info,notes,
      {"avant":avant,"arriere":arriere,"cote_gauche":cote_gauche,"cote_droit":cote_droit,"avant_gauche":avant_gauche,"avant_droit":avant_droit,"arriere_gauche":arriere_gauche,"arriere_droit":arriere_droit})
    try:
        result["assessment"] = create_assessment(result["rental_id"])
    except Exception as exc:
        result["assessment_error"] = str(exc)
    return result


def create_assessment(rental_id: str) -> dict[str, Any]:
    with connect() as con:
        rental = rowdict(con.execute("SELECT * FROM rentals WHERE id=?", (rental_id,)).fetchone())
        if not rental: raise HTTPException(status_code=404, detail="Location introuvable.")
        before_row = con.execute("SELECT id FROM inspections WHERE rental_id=? AND kind='INSPECTION_AVANT'", (rental_id,)).fetchone()
        after_row = con.execute("SELECT id FROM inspections WHERE rental_id=? AND kind='INSPECTION_APRES'", (rental_id,)).fetchone()
        if not before_row or not after_row: raise HTTPException(status_code=409, detail="Les deux inspections sont nécessaires au bilan.")
        before = get_inspection(con, before_row["id"]); after = get_inspection(con, after_row["id"])
        vehicle = get_vehicle_or_404(con, rental["vehicle_id"])
        # Avoid duplicate assessments for the same rental.
        existing = con.execute("SELECT id FROM assessments WHERE rental_id=?", (rental_id,)).fetchone()
        if existing: return assessment_detail(existing["id"])
    bmap = {p["angle"]:p for p in before["photos"]}; amap = {p["angle"]:p for p in after["photos"]}
    differences=[]
    for angle in ANGLES:
        pct, interpretation = image_diff(Path(bmap[angle]["file_path"]), Path(amap[angle]["file_path"]))
        differences.append({"angle":angle,"angle_label":ANGLE_LABELS[angle],"difference_percent":pct,"interpretation":interpretation,"before_hash":bmap[angle]["sha256"],"after_hash":amap[angle]["sha256"]})
    mileage_delta = after["mileage"] - before["mileage"]
    fuel_delta = round(after["fuel_level"] - before["fuel_level"],2)
    high = sum(1 for d in differences if d["difference_percent"] >= 22)
    medium = sum(1 for d in differences if 8 <= d["difference_percent"] < 22)
    conclusion = "Différences visuelles importantes à vérifier par un inspecteur." if high else "Différences visuelles à examiner par un inspecteur." if medium else "Aucune différence visuelle significative selon le seuil technique utilisé ; contrôle humain recommandé."
    summary={"conclusion":conclusion,"differences":differences,"mileage_before":before["mileage"],"mileage_after":after["mileage"],"mileage_delta":mileage_delta,
      "fuel_before":before["fuel_level"],"fuel_after":after["fuel_level"],"fuel_delta":fuel_delta,"human_review_required":True,
      "method":"OpenCV grayscale absolute-difference percentage after resizing and Gaussian blur; not a trained damage detector.",
      "note":"Les changements d'éclairage, d'angle et d'environnement influencent les scores. Toute suspicion doit être vérifiée humainement."}
    assessment_id=str(uuid.uuid4()); created=now_iso(); pdf=REPORT_DIR/f"bilan_{assessment_id}.pdf"
    combined = []
    for p in before["photos"]:
        combined.append({**p, "angle": f"Avant — {ANGLE_LABELS.get(p['angle'], p['angle'])}"})
    for p in after["photos"]:
        combined.append({**p, "angle": f"Après — {ANGLE_LABELS.get(p['angle'], p['angle'])}"})
    report_hash=make_pdf("Bilan final comparatif",vehicle,{"created_at":created,"mileage":after["mileage"],"fuel_level":after["fuel_level"],"engine_info":after["engine_info"],"oil_info":after["oil_info"],"tire_info":after["tire_info"],"dashboard_info":after["dashboard_info"],"interior_info":after["interior_info"],"exterior_info":after["exterior_info"],"notes":after["notes"]},combined,pdf,summary)
    event=event_anchor("BILAN_FINAL",assessment_id,{"vehicle_id":vehicle["id"],"rental_id":rental_id,"before_inspection_id":before["id"],"after_inspection_id":after["id"],"report_sha256":report_hash,"conclusion":conclusion})
    with connect() as con:
        con.execute("INSERT INTO assessments(id,vehicle_id,rental_id,before_inspection_id,after_inspection_id,created_at,summary_json,report_path,report_hash,hedera_status,hedera_tx,consensus_timestamp,hedera_message) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
          (assessment_id,vehicle["id"],rental_id,before["id"],after["id"],created,json.dumps(summary,ensure_ascii=False),str(pdf),report_hash,event["status"],event.get("transaction_id"),event.get("consensus_timestamp"),event.get("message")))
    return {"id":assessment_id,"created_at":created,"summary":summary,"report_hash":report_hash,"hedera":event}


def assessment_detail(assessment_id: str) -> dict[str, Any]:
    with connect() as con:
        row=rowdict(con.execute("SELECT * FROM assessments WHERE id=?", (assessment_id,)).fetchone())
        if not row: raise HTTPException(status_code=404,detail="Bilan introuvable.")
        row["summary"]=json.loads(row.pop("summary_json"))
        return row


@app.get("/api/inspections")
def list_inspections() -> list[dict[str, Any]]:
    with connect() as con:
        return [dict(r) for r in con.execute("SELECT i.*,v.registration,v.make,v.model FROM inspections i JOIN vehicles v ON v.id=i.vehicle_id ORDER BY i.created_at DESC").fetchall()]


@app.get("/api/inspections/{inspection_id}")
def inspection_detail(inspection_id: str) -> dict[str, Any]:
    with connect() as con:
        data=get_inspection(con,inspection_id)
        if not data: raise HTTPException(status_code=404, detail="Inspection introuvable.")
        vehicle = get_vehicle_or_404(con, data["vehicle_id"])
        data.update({key: vehicle[key] for key in ("registration", "make", "model", "year")})
        data["events"]=[dict(r) for r in con.execute("SELECT * FROM hedera_events WHERE reference_id=? ORDER BY created_at", (inspection_id,)).fetchall()]
        return data


@app.get("/api/assessments")
def list_assessments() -> list[dict[str, Any]]:
    with connect() as con:
        rows=con.execute("SELECT a.id,a.vehicle_id,a.rental_id,a.created_at,a.report_hash,a.hedera_status,a.hedera_tx,v.registration,v.make,v.model FROM assessments a JOIN vehicles v ON v.id=a.vehicle_id ORDER BY a.created_at DESC").fetchall()
        return [dict(r) for r in rows]


@app.get("/api/assessments/{assessment_id}")
def get_assessment(assessment_id: str) -> dict[str, Any]:
    return assessment_detail(assessment_id)


@app.get("/api/files/{file_id}")
def get_private_file(file_id: str, kind: str = "photo") -> FileResponse:
    # The app is a local prototype. Add authentication before deploying outside a trusted network.
    with connect() as con:
        if kind == "report":
            row=con.execute("SELECT report_path FROM inspections WHERE id=?",(file_id,)).fetchone()
            if not row or not row["report_path"]: row=con.execute("SELECT report_path FROM assessments WHERE id=?",(file_id,)).fetchone()
            if not row or not row["report_path"]: raise HTTPException(status_code=404,detail="Rapport introuvable.")
            path=safe_path(row["report_path"])
            return FileResponse(path, media_type="application/pdf", filename=path.name)
        row=con.execute("SELECT file_path,mime_type FROM photos WHERE id=?",(file_id,)).fetchone()
        if not row: raise HTTPException(status_code=404,detail="Photo introuvable.")
        path=safe_path(row["file_path"])
        return FileResponse(path, media_type=row["mime_type"], filename=path.name)


@app.get("/api/verify/{kind}/{record_id}")
def verify_record(kind: str, record_id: str) -> dict[str, Any]:
    if kind not in ("inspection", "assessment"):
        raise HTTPException(status_code=400, detail="kind doit être inspection ou assessment.")
    with connect() as con:
        table="inspections" if kind=="inspection" else "assessments"
        row=con.execute(f"SELECT report_path,report_hash,hedera_status,hedera_tx,consensus_timestamp FROM {table} WHERE id=?",(record_id,)).fetchone()
        if not row: raise HTTPException(status_code=404,detail="Enregistrement introuvable.")
        path=Path(row["report_path"]) if row["report_path"] else None
        exists=bool(path and path.exists())
        actual=sha256_file(path) if exists else None
        return {"record_id":record_id,"file_exists":exists,"stored_hash":row["report_hash"],"actual_hash":actual,
          "hash_matches":bool(exists and actual==row["report_hash"]),"hedera_status":row["hedera_status"],"transaction_id":row["hedera_tx"],"consensus_timestamp":row["consensus_timestamp"],
          "note":"La correspondance SHA-256 vérifie que le fichier correspond à l'empreinte enregistrée ; elle ne prouve pas à elle seule l'authenticité de la scène photographiée."}


@app.get("/api/events")
def list_events() -> list[dict[str, Any]]:
    with connect() as con:
        return [dict(r) for r in con.execute("SELECT * FROM hedera_events ORDER BY created_at DESC LIMIT 100").fetchall()]


@app.exception_handler(sqlite3.Error)
async def sqlite_exception_handler(_, exc: sqlite3.Error):
    return JSONResponse(status_code=500, content={"detail":"Erreur de base de données.","error":str(exc)})
