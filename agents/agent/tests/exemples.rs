//! Les exemples du contrat (`docs/agents-contrat-v1.json`) : même fichier que les tests Python.

use agent::contrat::{
    CorpsErreur, DemandeModele, DemandeOutil, Ligne, LigneModele, Mission, ReponseModele,
    ReponseOutil, Sante,
};
use serde::{Serialize, de::DeserializeOwned};
use serde_json::Value;

fn aller_retour<T: Serialize + DeserializeOwned>(nom: &str, exemple: &Value) {
    let objet: T = serde_json::from_value(exemple.clone())
        .unwrap_or_else(|e| panic!("exemple « {nom} » illisible : {e}"));
    let relu = serde_json::to_value(&objet).unwrap();
    assert_eq!(
        &relu, exemple,
        "exemple « {nom} » changé par l'aller-retour"
    );
}

#[test]
fn exemples_du_contrat() {
    let ex: Value = serde_json::from_str(include_str!("../../../docs/agents-contrat-v1.json"))
        .expect("le fichier d'exemples est du JSON");
    aller_retour::<Mission>("mission", &ex["mission"]);
    for nom in ["ligne_texte", "ligne_fin", "ligne_erreur"] {
        aller_retour::<Ligne>(nom, &ex[nom]);
    }
    aller_retour::<DemandeModele>("demande_modele", &ex["demande_modele"]);
    aller_retour::<ReponseModele>("reponse_modele", &ex["reponse_modele"]);
    for ligne in ex["demande_modele_flux_lignes"].as_array().unwrap() {
        aller_retour::<LigneModele>("demande_modele_flux_lignes", ligne);
    }
    aller_retour::<DemandeOutil>("demande_outil", &ex["demande_outil"]);
    aller_retour::<ReponseOutil>("reponse_outil", &ex["reponse_outil"]);
    aller_retour::<Sante>("sante", &ex["sante"]);
    aller_retour::<CorpsErreur>("erreur", &ex["erreur"]);
}

/// Les exemples que les tests ci-dessus lisent. Un exemple ajouté au JSON doit l'être ici,
/// avec son type.
const COUVERTS: [&str; 11] = [
    "mission",
    "ligne_texte",
    "ligne_fin",
    "ligne_erreur",
    "demande_modele",
    "reponse_modele",
    "demande_modele_flux_lignes",
    "demande_outil",
    "reponse_outil",
    "sante",
    "erreur",
];

#[test]
fn tous_les_exemples_sont_couverts() {
    let ex: Value =
        serde_json::from_str(include_str!("../../../docs/agents-contrat-v1.json")).unwrap();
    let mut non_couverts: Vec<&String> = ex
        .as_object()
        .unwrap()
        .keys()
        .filter(|k| !COUVERTS.contains(&k.as_str()))
        .collect();
    non_couverts.sort();
    assert!(
        non_couverts.is_empty(),
        "exemples du contrat sans test dans exemples.rs : {non_couverts:?}"
    );
    for k in COUVERTS {
        assert!(ex.get(k).is_some(), "exemple « {k} » retiré du JSON");
    }
}

#[test]
fn message_ignore_les_champs_inconnus_et_n_en_renvoie_pas() {
    use agent::contrat::MessageLlm;
    let m: MessageLlm =
        serde_json::from_str(r#"{"role":"assistant","content":null,"nouveau":1}"#).unwrap();
    assert_eq!(
        serde_json::to_value(&m).unwrap(),
        serde_json::json!({"role": "assistant"})
    );
}
