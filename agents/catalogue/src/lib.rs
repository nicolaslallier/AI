//! Les agents du portail : un binaire par agent, tous sur la boucle par défaut aujourd'hui.

use agent::serveur::Tourner;

/// Les agents de `agents.yaml` (un test vérifie l'égalité).
pub const NOMS: [&str; 13] = [
    "spec",
    "orchestrateur",
    "plan",
    "taches",
    "tests",
    "code",
    "revue",
    "architecte",
    "challenger",
    "securite",
    "doc",
    "pm",
    "tri",
];

/// Le travail d'un agent. Un agent sur mesure gagne ici sa branche et son module.
pub fn tourner(nom: &str) -> Option<Tourner> {
    NOMS.contains(&nom)
        .then_some(agent::boucle::par_defaut as Tourner)
}

pub async fn principal(nom: &'static str) {
    agent::serveur::servir(nom, tourner(nom).expect("agent inconnu du catalogue")).await
}
