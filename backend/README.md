# Backend ODHMEN 7A9EK

Consultez le `README.md` à la racine pour les étapes d'installation, le lancement sur Windows et la configuration Hedera.

Démarrage depuis ce dossier :

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

API : `http://127.0.0.1:8001/api/health`
