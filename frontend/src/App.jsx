import { useEffect, useMemo, useState } from 'react';
import axios from 'axios';

const API = import.meta.env.VITE_API_URL || '/api';
const angles = [
  ['avant', 'Avant'], ['arriere', 'Arrière'], ['cote_gauche', 'Côté gauche'], ['cote_droit', 'Côté droit'],
  ['avant_gauche', 'Avant gauche'], ['avant_droit', 'Avant droit'], ['arriere_gauche', 'Arrière gauche'], ['arriere_droit', 'Arrière droit']
];
const emptyInspection = { make: '', model: '', registration: '', year: '', mileage: '', fuel_level: 50, engine_info: '', oil_info: '', tire_info: '', dashboard_info: '', interior_info: '', exterior_info: '', notes: '' };

function apiErrorMessage(error, fallback) {
  const detail = error?.response?.data?.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail)) {
    return detail.map(item => item.msg).filter(Boolean).join(' · ') || fallback;
  }
  if (!error?.response) return 'Impossible de joindre le backend. Vérifiez que FastAPI est démarré.';
  return `${fallback} (HTTP ${error.response.status})`;
}

function App() {
  const [page, setPage] = useState('dashboard');
  const [dashboard, setDashboard] = useState(null);
  const [rentals, setRentals] = useState([]);
  const [inspections, setInspections] = useState([]);
  const [assessments, setAssessments] = useState([]);
  const [loading, setLoading] = useState(false);
  const [toast, setToast] = useState(null);
  const [inspectionMode, setInspectionMode] = useState('before');
  const [selectedRental, setSelectedRental] = useState('');
  const [inspectionForm, setInspectionForm] = useState(emptyInspection);
  const [photoFiles, setPhotoFiles] = useState({});
  const [submission, setSubmission] = useState(null);
  const [verifyResult, setVerifyResult] = useState(null);
  const [reportFilter, setReportFilter] = useState('all');

  const notify = (type, message) => {
    setToast({ type, message });
    window.setTimeout(() => setToast(null), 5500);
  };
  const get = async (url) => (await axios.get(`${API}${url}`)).data;
  const refresh = async () => {
    setLoading(true);
    try {
      const [d, r, i, a] = await Promise.all([
        get('/dashboard'), get('/rentals?status=active'), get('/inspections'), get('/assessments')
      ]);
      setDashboard(d); setRentals(r); setInspections(i); setAssessments(a);
    } catch (error) {
      notify('danger', error?.response?.data?.detail || 'Impossible de joindre le backend. Vérifiez que FastAPI est démarré.');
    } finally { setLoading(false); }
  };
  useEffect(() => { refresh(); }, []);

  const filteredInspections = useMemo(() => reportFilter === 'all' ? inspections : inspections.filter(i => i.kind === reportFilter), [inspections, reportFilter]);

  const submitInspection = async (event) => {
    event.preventDefault(); setSubmission(null);
    if (Object.keys(photoFiles).length !== 8 || angles.some(([key]) => !photoFiles[key])) {
      notify('warning', 'Ajoutez une photo pour chacun des 8 angles avant de valider.'); return;
    }
    if (inspectionMode === 'after' && !selectedRental) { notify('warning', 'Choisissez une location active.'); return; }
    const form = new FormData();
    Object.entries(inspectionForm).forEach(([key, value]) => {
      if (key !== 'year' || value !== '') form.append(key, String(value ?? ''));
    });
    angles.forEach(([key]) => form.append(key, photoFiles[key]));
    setLoading(true);
    try {
      const path = inspectionMode === 'before' ? '/inspections/before' : `/rentals/${selectedRental}/after-inspection`;
      const response = (await axios.post(`${API}${path}`, form)).data;
      setSubmission(response); setPhotoFiles({}); setInspectionForm(emptyInspection);
      notify('success', inspectionMode === 'before' ? 'Inspection avant enregistrée.' : 'Inspection retour enregistrée.');
      await refresh();
      setPage('reports');
    } catch (error) { notify('danger', apiErrorMessage(error, 'Échec de l’enregistrement de l’inspection.')); }
    finally { setLoading(false); }
  };

  const verify = async (kind, id) => {
    try { setVerifyResult(await get(`/verify/${kind}/${id}`)); } catch (error) { notify('danger', error?.response?.data?.detail || 'Vérification impossible.'); }
  };
  const pdfUrl = (id) => `${API}/files/${id}?kind=report`;
  const photoUrl = (id) => `${API}/files/${id}?kind=photo`;

  const nav = [
    { id: 'dashboard', icon: '▦', label: 'Tableau de bord' },
    { id: 'inspection', icon: '◎', label: 'Nouvelle inspection' },
    { id: 'reports', icon: '▤', label: 'Rapports & bilans' }
  ];

  return <div className="app-shell">
    <aside className="sidebar">
      <div className="brand"><div className="brand-mark" role="img" aria-label="Voiture"><svg width="35" height="35" viewBox="0 0 48 48" aria-hidden="true"><path d="M9 26.5 12.3 18c.7-1.8 2.4-3 4.3-3h14.8c1.7 0 3.2.9 4 2.4l4.1 7.1 2.5 1.7c1.2.8 2 2.2 2 3.7v5.4c0 1.2-1 2.2-2.2 2.2h-2.1a5.7 5.7 0 0 1-11.2 0H19.5a5.7 5.7 0 0 1-11.2 0H6.2A2.2 2.2 0 0 1 4 34.3v-4.1c0-1.4.8-2.7 2.1-3.3L9 26.5Zm5.2-7-2.2 5.7h24.8l-3.1-5.4a2.7 2.7 0 0 0-2.3-1.3H16.6c-1.1 0-2.1.7-2.4 1.7ZM14 37a2.7 2.7 0 1 0 0-5.4 2.7 2.7 0 0 0 0 5.4Zm19.8 0a2.7 2.7 0 1 0 0-5.4 2.7 2.7 0 0 0 0 5.4Z" fill="currentColor"/><path d="m14 25.2 2-5.1c.1-.4.5-.7.9-.7h7v5.8H14Zm12-5.8h5.3c.4 0 .8.2 1 .6l3 5.2H26v-5.8Z" fill="#21191e"/><path d="M7 29h4M38 29h4" stroke="#f8c3c4" strokeWidth="1.7" strokeLinecap="round"/></svg></div><div><div className="brand-name">ODHMEN <span>7A9EK</span></div><small>INSPECTION INTELLIGENTE</small></div></div>
      <div className="side-label">ESPACE AGENCE</div>
      <nav>{nav.map(item => <button key={item.id} className={`nav-item ${page === item.id ? 'active' : ''}`} onClick={() => setPage(item.id)}><span className="nav-icon">{item.icon}</span>{item.label}</button>)}</nav>
      <div className="side-legal">La confiance, preuves à l’appui.</div>
    </aside>
    <main className="main-content">
      <header className="topbar"><div><div className="eyebrow">AGENCE D’INSPECTION AUTOMOBILE</div><h1>{nav.find(n => n.id === page)?.label || 'Espace agence'}</h1></div></header>
      {toast && <div className={`alert alert-${toast.type} toast-message`} role="alert">{toast.message}<button onClick={() => setToast(null)}>×</button></div>}
      {loading && <div className="loading-line"><span /></div>}

      {page === 'dashboard' && <section>
        <div className="welcome-panel"><div><div className="eyebrow red">VOTRE ESPACE DE CONTRÔLE</div><h2>La transparence commence<br />par une <span>preuve vérifiable.</span></h2><p>Suivez les inspections, comparez les états et retrouvez l’historique de chaque véhicule.</p><button className="btn-red" onClick={() => setPage('inspection')}>＋ Nouvelle inspection</button></div><div className="welcome-art"><div className="orbit orbit-one"/><div className="orbit orbit-two"/><div className="car-symbol">🚘</div><div className="art-chip chip-top">✦ IA · Analyse visuelle</div><div className="art-chip chip-bottom">◇ SHA-256 · Hedera</div></div></div>
        <div className="section-head"><div><h3>Vue d’ensemble</h3><p>Les indicateurs de votre agence</p></div><button className="btn-outline" onClick={refresh}>↻ Actualiser</button></div>
        <div className="stats-grid">
          <StatCard label="Total inspections" value={dashboard?.inspections_total ?? '—'} caption="Rapports enregistrés" icon="◎" />
          <StatCard label="Avant location" value={dashboard?.inspections_before ?? '—'} caption="Contrôles initiaux" icon="↗" accent />
          <StatCard label="Retours" value={dashboard?.inspections_after ?? '—'} caption="Contrôles au retour" icon="↙" />
          <StatCard label="Locations actives" value={dashboard?.rentals_active ?? '—'} caption="En attente d’un retour" icon="↻" />
        </div>
        <div className="dashboard-columns"><div className="panel"><div className="panel-heading"><div><h3>Inspections récentes</h3><p>Dernières opérations enregistrées</p></div><button className="text-action" onClick={() => setPage('reports')}>Tout voir ↗</button></div>
          {dashboard?.recent_inspections?.length ? <div className="table-responsive"><table className="table custom-table"><thead><tr><th>Véhicule</th><th>Type</th><th>Date</th><th>Statut</th></tr></thead><tbody>{dashboard.recent_inspections.map(i => <tr key={i.id}><td><strong>{i.make} {i.model}</strong><small>{i.registration}</small></td><td>{i.kind === 'INSPECTION_AVANT' ? 'Avant location' : 'Au retour'}</td><td>{new Date(i.created_at).toLocaleDateString('fr-FR')}</td><td><StatusPill status={i.hedera_status} /></td></tr>)}</tbody></table></div> : <EmptyState title="Aucune inspection" description="Enregistrez une première inspection pour démarrer l’historique." action="Lancer une inspection" onClick={() => setPage('inspection')} />}
        </div><div className="panel ledger-panel"><div className="panel-heading"><div><h3>Traçabilité des inspections</h3><p>Événements d’intégrité</p></div><span className="ledger-icon">◇</span></div><div className="ledger-status"><div><strong>Rapports et empreintes vérifiables</strong><p>Retrouvez les preuves et les événements enregistrés pour chaque inspection.</p></div></div><div className="ledger-note">Les photos et rapports restent sur le serveur. Les empreintes et métadonnées sont prévues pour HCS.</div><button className="btn-outline full-width" onClick={() => setPage('reports')}>Consulter les traces</button></div></div>
      </section>}

      {page === 'inspection' && <section>
        <div className="inspection-intro"><div className="eyebrow red">PROCESSUS DE CONTRÔLE</div><h2>Chaque détail compte.</h2><p>Huit angles standardisés, des observations mécaniques et une trace vérifiable.</p></div>
        <div className="stepper"><div className="step active"><span>01</span><div><strong>Véhicule & inspection</strong><small>Caractéristiques + contrôles</small></div></div><div className="step-line"/><div className="step active"><span>02</span><div><strong>Photos</strong><small>8 angles standardisés</small></div></div><div className="step-line"/><div className="step"><span>03</span><div><strong>Rapport</strong><small>PDF et empreintes</small></div></div></div>
        <div className="panel form-panel"><div className="panel-heading"><div><h3>Nouvelle inspection</h3><p>Les photos sont définitives après la validation de l’inspection.</p></div></div>
          <div className="mode-tabs"><button className={inspectionMode === 'before' ? 'selected' : ''} onClick={() => { setInspectionMode('before'); setPhotoFiles({}); setSubmission(null); }}>Avant location</button><button className={inspectionMode === 'after' ? 'selected' : ''} onClick={() => { setInspectionMode('after'); setPhotoFiles({}); setSubmission(null); }}>Retour de location</button></div>
          <form onSubmit={submitInspection}>
            <div className="form-grid mt-3">
              {inspectionMode === 'before' && <>
                <Field label="Marque *"><input required maxLength="60" value={inspectionForm.make} onChange={e => setInspectionForm({...inspectionForm,make:e.target.value})} placeholder="Toyota" /></Field>
                <Field label="Modèle *"><input required maxLength="80" value={inspectionForm.model} onChange={e => setInspectionForm({...inspectionForm,model:e.target.value})} placeholder="Yaris" /></Field>
                <Field label="Immatriculation *"><input required minLength="2" maxLength="20" value={inspectionForm.registration} onChange={e => setInspectionForm({...inspectionForm,registration:e.target.value})} placeholder="123 تونس 4567" /></Field>
                <Field label="Année du véhicule"><input type="number" min="1950" max="2100" value={inspectionForm.year} onChange={e => setInspectionForm({...inspectionForm,year:e.target.value})} placeholder="2024" /></Field>
              </>}
              {inspectionMode === 'after' && <Field label="Location active *"><select required value={selectedRental} onChange={e => setSelectedRental(e.target.value)}><option value="">Sélectionner une location active</option>{rentals.map(r => <option key={r.id} value={r.id}>{r.registration} — {r.make} {r.model} · Début {new Date(r.started_at).toLocaleDateString('fr-FR')}</option>)}</select></Field>}
              <Field label="Kilométrage actuel (km) *"><input type="number" min="0" required value={inspectionForm.mileage} onChange={e => setInspectionForm({...inspectionForm,mileage:e.target.value})} /></Field>
              <Field label="Carburant (%) *"><input type="number" min="0" max="100" required value={inspectionForm.fuel_level} onChange={e => setInspectionForm({...inspectionForm,fuel_level:e.target.value})} /></Field>
              <Field label="État du moteur"><input value={inspectionForm.engine_info} onChange={e => setInspectionForm({...inspectionForm,engine_info:e.target.value})} placeholder="Bruit, fuite, observation..." /></Field>
              <Field label="État / niveau de l’huile"><input value={inspectionForm.oil_info} onChange={e => setInspectionForm({...inspectionForm,oil_info:e.target.value})} placeholder="Niveau, couleur, fuite..." /></Field>
              <Field label="État des pneus"><input value={inspectionForm.tire_info} onChange={e => setInspectionForm({...inspectionForm,tire_info:e.target.value})} placeholder="Usure, pression..." /></Field>
              <Field label="Voyants du tableau de bord"><input value={inspectionForm.dashboard_info} onChange={e => setInspectionForm({...inspectionForm,dashboard_info:e.target.value})} placeholder="Aucun / détail des voyants" /></Field>
              <Field label="État intérieur"><input value={inspectionForm.interior_info} onChange={e => setInspectionForm({...inspectionForm,interior_info:e.target.value})} placeholder="Sièges, tableau de bord..." /></Field>
              <Field label="État extérieur"><input value={inspectionForm.exterior_info} onChange={e => setInspectionForm({...inspectionForm,exterior_info:e.target.value})} placeholder="Carrosserie, vitres..." /></Field>
              <Field label="Notes de l’inspecteur" wide><textarea rows="2" value={inspectionForm.notes} onChange={e => setInspectionForm({...inspectionForm,notes:e.target.value})} placeholder="Observations complémentaires" /></Field>
            </div>
            <div className="photo-section-head"><div><h3>Photos obligatoires <span>08</span></h3><p>JPG, PNG ou WEBP · maximum {12} Mo par photo. Utilisez les mêmes angles avant et après.</p></div><div className={`photo-count ${Object.keys(photoFiles).length === 8 ? 'complete' : ''}`}>{Object.keys(photoFiles).length}/8</div></div>
            <div className="photo-grid">{angles.map(([key, label], index) => <label className={`photo-upload ${photoFiles[key] ? 'has-file' : ''}`} key={key}><input type="file" accept="image/jpeg,image/png,image/webp" onChange={e => setPhotoFiles({...photoFiles,[key]:e.target.files?.[0]})} /><div className="photo-index">{String(index + 1).padStart(2,'0')}</div>{photoFiles[key] ? <div className="photo-preview"><img src={URL.createObjectURL(photoFiles[key])} alt={label}/><span>✓ Photo ajoutée</span></div> : <div className="upload-placeholder"><span className="upload-icon">＋</span><strong>{label}</strong><small>Cliquer pour choisir</small></div>}</label>)}</div>
            <div className="immutable-notice"><span>♢</span><div><strong>Validation définitive</strong><p>Après validation, les photos originales seront conservées en lecture seule. Vérifiez chaque angle avant d’envoyer.</p></div></div>
            <div className="form-actions"><button type="button" className="btn-outline" onClick={() => {setPhotoFiles({});setInspectionForm(emptyInspection);}}>Réinitialiser le formulaire</button><button type="submit" className="btn-red" disabled={loading}>{loading ? 'Enregistrement…' : 'Valider l’inspection →'}</button></div>
          </form>
        </div>
      </section>}

      {page === 'reports' && <section>
        <div className="section-head"><div><h3>Rapports & bilans</h3><p>Consultez les inspections, les bilans finaux et vérifiez l’intégrité des fichiers.</p></div><button className="btn-red" onClick={() => setPage('inspection')}>＋ Inspection</button></div>
        {submission && <div className="submission-banner"><div className="submission-check">✓</div><div><strong>Inspection enregistrée</strong><p>Rapport : {submission.report_hash?.slice(0, 20)}… · Hedera : {submission.hedera?.status || '—'}</p></div><a className="btn-outline" href={pdfUrl(submission.inspection_id)} target="_blank" rel="noreferrer">Ouvrir le PDF ↗</a></div>}
        {assessments.length > 0 && <div className="panel assessment-feature"><div className="assessment-symbol">✧</div><div className="assessment-feature-main"><div className="eyebrow red">COMPARAISON IA</div><h3>Bilans comparatifs finaux</h3><p>Les bilans sont générés après l’inspection de retour à partir des deux séries de photos.</p><div className="assessment-list">{assessments.map(a => <div className="assessment-row" key={a.id}><div><strong>{a.make} {a.model} · {a.registration}</strong><small>{new Date(a.created_at).toLocaleString('fr-FR')}</small></div><StatusPill status={a.hedera_status}/><a href={pdfUrl(a.id)} target="_blank" rel="noreferrer" className="btn-table">Bilan PDF ↗</a><button className="btn-table" onClick={() => verify('assessment',a.id)}>Vérifier</button></div>)}</div></div></div>}
        <div className="panel"><div className="table-toolbar"><div><h3>Rapports d’inspection</h3><p>Rapports avant location et au retour</p></div><select className="filter-select" value={reportFilter} onChange={e => setReportFilter(e.target.value)}><option value="all">Tous les rapports</option><option value="INSPECTION_AVANT">Avant location</option><option value="INSPECTION_APRES">Au retour</option></select></div>
          {filteredInspections.length ? <div className="table-responsive"><table className="table custom-table"><thead><tr><th>Véhicule</th><th>Type de rapport</th><th>Date</th><th>Empreinte SHA-256</th><th>Hedera</th><th>Actions</th></tr></thead><tbody>{filteredInspections.map(i => <tr key={i.id}><td><strong>{i.make} {i.model}</strong><small>{i.registration}</small></td><td>{i.kind === 'INSPECTION_AVANT' ? 'Avant location' : 'Retour de location'}</td><td>{new Date(i.created_at).toLocaleDateString('fr-FR')}</td><td><code>{(i.report_hash || 'En attente').slice(0,14)}…</code></td><td><StatusPill status={i.hedera_status}/></td><td><a className="btn-table link-button" href={pdfUrl(i.id)} target="_blank" rel="noreferrer">PDF ↗</a><button className="btn-table" onClick={() => verify('inspection',i.id)}>Vérifier</button></td></tr>)}</tbody></table></div> : <EmptyState title="Aucun rapport disponible" description="Les rapports apparaissent ici après la validation d’une inspection." action="Créer une inspection" onClick={() => setPage('inspection')} />}
        </div>
        {verifyResult && <div className="panel verification-panel"><div className="panel-heading"><div><h3>Vérification d’intégrité</h3><p>Enregistrement : {verifyResult.record_id}</p></div><button className="btn-outline" onClick={() => setVerifyResult(null)}>Fermer ×</button></div><div className="verification-result"><span className={`verify-icon ${verifyResult.hash_matches ? 'match' : 'mismatch'}`}>{verifyResult.hash_matches ? '✓' : '!'}</span><div><strong>{verifyResult.hash_matches ? 'Empreinte SHA-256 correspondante' : 'Empreinte absente ou différente'}</strong><p>{verifyResult.note}</p></div></div><div className="detail-grid"><Detail label="Fichier présent" value={verifyResult.file_exists ? 'Oui' : 'Non'}/><Detail label="Correspondance de hash" value={verifyResult.hash_matches ? 'Oui' : 'Non'}/><Detail label="Statut Hedera" value={verifyResult.hedera_status}/><Detail label="Transaction ID" value={verifyResult.transaction_id || 'Aucune'}/><Detail label="Timestamp consensus" value={verifyResult.consensus_timestamp || 'Non disponible'}/></div></div>}
      </section>}
      <footer className="app-footer"><span>ODHMEN 7A9EK © {new Date().getFullYear()}</span><span>Inspecter · Comparer · Rapporter · Vérifier</span></footer>
    </main>
  </div>;
}

function StatCard({label,value,caption,icon,accent}) { return <div className={`stat-card ${accent ? 'accent-card' : ''}`}><div className="stat-top"><span>{label}</span><span className="stat-icon">{icon}</span></div><div className="stat-number">{value}</div><div className="stat-caption"><span className="tiny-bullet"/> {caption}</div></div>; }
function Field({label,children,wide}) { return <label className={`field ${wide?'wide':''}`}><span>{label}</span>{children}</label>; }
function StatusPill({status}) { const map = {confirmed:['Confirmé','confirmed'],submitted:['Envoyé','pending'],simulation:['Simulation locale','simulation'],pending:['En attente','pending'],failed:['Échec','failed']}; const [label,cls]=map[status]||[status||'Inconnu','pending']; return <span className={`status-pill ${cls}`}><i/>{label}</span>; }
function EmptyState({title,description,action,onClick}) { return <div className="empty-state"><div className="empty-icon">⌕</div><strong>{title}</strong><p>{description}</p>{action&&<button className="btn-outline" onClick={onClick}>{action}</button>}</div>; }

export default App;
