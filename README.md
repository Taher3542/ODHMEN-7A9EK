# ODHMEN 7A9EK — Inspection automobile intelligente

Application web prototype avec React + Vite, FastAPI/Python, SQLite, OpenCV, génération PDF et ancrage Hedera HCS configurable.

## Ce qui est inclus

- Tableau de bord des inspections et des locations actives.
- Saisie des caractéristiques du véhicule directement lors de l’inspection initiale.
- Inspection avant location avec 8 photos obligatoires (angles prédéfinis).
- Inspection au retour avec une nouvelle série de 8 photos.
- Les photos initiales restent conservées et ne sont pas remplacées par l'inspection retour.
- Rapports PDF pour les inspections avant/après.
- Bilan comparatif final qui calcule un score technique de différence visuelle via OpenCV.
- Empreintes SHA-256 des photos et des rapports.
- Historique, téléchargement de PDF et vérification de l'empreinte.
- Service Hedera HCS configurable : mode local clairement identifié sans clés ; tentative d'envoi réelle lorsque les credentials et le topic sont renseignés.

## Prérequis Windows

- Python 3.11 ou 3.12 recommandé.
- Node.js LTS et npm.
- Visual Studio Code (facultatif mais pratique).
- Un compte Hedera testnet et un topic HCS uniquement si vous voulez tester les transactions réelles.

## Démarrage rapide sous Windows

Double-cliquez sur `start-backend.bat`, puis sur `start-frontend.bat` : gardez les deux fenêtres ouvertes. Au premier lancement, le script backend crée l'environnement Python et installe ses dépendances. Ouvrez ensuite l'adresse locale affichée par Vite dans la fenêtre frontend (par exemple `http://127.0.0.1:5173` ou `http://127.0.0.1:5174` si le port est déjà utilisé). Pour arrêter les serveurs, faites `Ctrl+C` dans chacune des fenêtres.

## Lancer le backend

Dans VS Code, ouvrez le dossier `odhmen_7a9ek`, puis ouvrez un terminal PowerShell :

```powershell
cd backend
py -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -r requirements.txt
Copy-Item .env.example .env
uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

Si PowerShell bloque l'activation du venv, vous pouvez utiliser directement :

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8001 --reload
```

API : `http://127.0.0.1:8001/api/health`
Documentation interactive : `http://127.0.0.1:8001/docs`

La base SQLite et les fichiers privés sont créés automatiquement dans `backend/data/` au premier démarrage. Ne supprimez pas ce dossier si vous souhaitez conserver vos données.

## Lancer le frontend

Ouvrez un **deuxième terminal** :

```powershell
cd frontend
npm install
npm run dev
```

Ouvrez l'URL fournie par Vite (normalement `http://127.0.0.1:5173`). En développement, Vite transmet automatiquement les requêtes `/api` à FastAPI sur `http://127.0.0.1:8001`. Cela fonctionne aussi si Vite choisit un autre port parce que le port 5173 est déjà occupé.

Pour une installation frontend indépendante de Vite, créez `frontend/.env.local` afin de définir l'URL de l'API :

```env
VITE_API_URL=http://127.0.0.1:8001/api
```

## Utiliser l'application

1. Ouvrez **Nouvelle inspection** et choisissez **Avant location**.
2. Saisissez la marque, le modèle, l’immatriculation et l’année du véhicule, puis le kilométrage, le carburant et les observations.
3. Ajoutez exactement 8 photos, une par angle.
4. Validez : l'application crée la location, enregistre les photos, calcule les empreintes et génère un PDF.
5. Au retour, choisissez **Retour de location**, sélectionnez la location active et chargez les mêmes 8 angles.
6. Le backend génère le rapport de retour puis tente de produire automatiquement le bilan final.
7. Retrouvez rapports, bilan et vérification dans **Rapports & bilans**.

## Configuration Hedera HCS réelle

L'application fonctionne en local sans compte Hedera : les événements seront marqués `simulation` et **ne seront pas écrits sur la blockchain**.

Pour tester un ancrage réel :

1. Créez/ouvrez un compte de développeur Hedera et obtenez des identifiants de testnet.
2. Créez ou récupérez le `Topic ID` HCS sur le réseau testnet.
3. Renseignez dans `backend/.env` :

```env
HEDERA_NETWORK=testnet
HEDERA_OPERATOR_ID=0.0.xxxxx
HEDERA_OPERATOR_KEY=your_testnet_private_key
HEDERA_TOPIC_ID=0.0.yyyyy
```

4. Installez le backend selon `requirements.txt`, puis redémarrez Uvicorn.
5. Vérifiez `http://127.0.0.1:8001/api/health` : `hedera_configured` doit être `true`.
6. Faites une nouvelle inspection de test et vérifiez que l'événement a un statut Hedera réel. Les transactions consomment le solde testnet ; elles ne sont pas simulées lorsque les clés sont configurées.

Le code utilise `hiero-sdk-python` et son interface HCS. Le SDK étant encore en évolution, si votre version installée expose différemment la réponse d'une transaction, consultez le guide de l'API et ajustez `backend/app/hedera_service.py`. L'application ne fabrique jamais un consensus timestamp : elle n'affiche que les informations retournées par le SDK.

## Important — limites du prototype

- La comparaison OpenCV actuelle est un **score de différence visuelle**, pas un modèle spécialisé entraîné à détecter des dommages. Éclairage, cadrage, ombres et angle peuvent influencer le résultat. Toute anomalie doit être vérifiée par un inspecteur.
- Une empreinte SHA-256 permet de vérifier qu'un fichier correspond à l'empreinte enregistrée. Elle ne prouve pas que la photo représente fidèlement la scène ni qui est responsable d'un dommage.
- Le mode Hedera n'est réel que si les credentials et un `Topic ID` valides sont fournis et que la transaction aboutit.
- Cette version est un prototype de démonstration **sans authentification utilisateur**. Les endpoints de fichiers ne doivent pas être exposés sur Internet avant l'ajout d'une authentification, d'autorisations par rôle, HTTPS, sauvegardes et mesures de protection supplémentaires.
- L'application conserve les photos validées en lecture seule dans son flux normal. Pour un déploiement réel, le stockage doit aussi être protégé contre toute modification directe sur le système de fichiers, avec sauvegardes et contrôle d'accès.
- Les coûts de réparation et l'estimation automatique des dommages ne sont pas inclus, afin d'éviter d'inventer un prix sans tarif documenté.

## Lancer les tests backend

Après installation des dépendances de développement :

```powershell
cd backend
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Les tests couvrent le mode local Hedera, les immatriculations en doublon, le cycle complet avant/après, la génération du bilan et la vérification des empreintes.

## Structure

```text
odhmen_7a9ek/
├── README.md
├── backend/
│   ├── app/
│   │   ├── main.py
│   │   └── hedera_service.py
│   ├── .env.example
│   └── requirements.txt
└── frontend/
    ├── index.html
    ├── package.json
    └── src/
        ├── App.jsx
        ├── main.jsx
        └── styles.css
```
