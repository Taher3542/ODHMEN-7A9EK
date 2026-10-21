"""Optional HCS anchoring service. Local mode is explicitly marked as simulated."""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone
from typing import Any


def hedera_configured() -> bool:
    return all(os.getenv(k, "").strip() for k in ("HEDERA_OPERATOR_ID", "HEDERA_OPERATOR_KEY", "HEDERA_TOPIC_ID"))


def submit_event(payload: dict[str, Any]) -> dict[str, Any]:
    """Submit a compact event to HCS when credentials are configured.

    The SDK is imported lazily so the app remains usable in local development without keys.
    No image or PDF content is sent to Hedera, only metadata and hashes.
    """
    if not hedera_configured():
        return {
            "status": "simulation",
            "transaction_id": None,
            "consensus_timestamp": None,
            "message": "Mode local : événement non envoyé à Hedera. Configurez les variables HEDERA_* pour un ancrage réel.",
        }
    try:
        from hiero_sdk_python import (  # type: ignore[import-not-found]
            AccountId, Client, Network, PrivateKey, TopicId, TopicMessageSubmitTransaction
        )

        network_name = os.getenv("HEDERA_NETWORK", "testnet").lower()
        if network_name not in ("testnet", "mainnet"):
            raise ValueError("HEDERA_NETWORK doit être testnet ou mainnet.")
        client = Client(Network(network_name))
        operator_id = AccountId.from_string(os.environ["HEDERA_OPERATOR_ID"])
        operator_key = PrivateKey.from_string(os.environ["HEDERA_OPERATOR_KEY"])
        topic_id = TopicId.from_string(os.environ["HEDERA_TOPIC_ID"])
        client.set_operator(operator_id, operator_key)
        message = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(message.encode("utf-8")) > 1024:
            raise ValueError("Le message HCS dépasse 1024 octets. Réduisez les métadonnées.")
        tx = (
            TopicMessageSubmitTransaction(topic_id=topic_id, message=message)
            .freeze_with(client)
            .sign(operator_key)
        )
        response = tx.execute(client)
        txid = getattr(response, "transaction_id", None)
        # SDK response attributes differ by version. Never manufacture a consensus timestamp.
        txid_text = str(txid) if txid is not None else None
        consensus_ts = None
        transaction_status = "submitted" if txid_text else "failed"
        receipt_message = "Transaction soumise ; confirmation réseau à vérifier."
        try:
            receipt = response.get_receipt(client)
            receipt_status = getattr(receipt, "status", None)
            status_text = str(receipt_status).upper() if receipt_status is not None else ""
            if "SUCCESS" in status_text:
                transaction_status = "confirmed"
                receipt_message = "Réception Hedera signalée comme réussie."
            elif receipt_status is not None:
                transaction_status = "failed"
                receipt_message = f"Hedera a retourné le statut {receipt_status}."
            ts = getattr(receipt, "consensus_timestamp", None)
            consensus_ts = str(ts) if ts is not None else None
        except Exception:
            # Ne marquez pas la transaction comme confirmée si la lecture du reçu échoue.
            transaction_status = "submitted" if txid_text else "failed"
        return {
            "status": transaction_status,
            "transaction_id": txid_text,
            "consensus_timestamp": consensus_ts,
            "message": receipt_message if txid_text else "Le SDK n'a pas retourné d'identifiant de transaction.",
        }

    except Exception as exc:
        return {
            "status": "failed",
            "transaction_id": None,
            "consensus_timestamp": None,
            "message": f"Échec Hedera : {type(exc).__name__}: {exc}",
        }
