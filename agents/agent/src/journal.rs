//! Journal JSON, une ligne par événement sur la sortie standard (Docker horodate, Loki garde).
//!
//! Garantie par les types : le message est un `&'static str` et le reste des nombres. Aucun
//! texte venu d'une mission, du modèle ou du portail (prompt, réponse, sortie d'outil, erreur)
//! ne peut donc entrer dans une ligne. `agent` est le nom compilé du binaire ; `mission` est
//! l'identifiant opaque donné par le portail (échappé par `serde_json`).

use serde_json::{Map, Value};

fn ligne(
    niveau: &'static str,
    agent: &'static str,
    mission: &str,
    message: &'static str,
    compteurs: &[(&'static str, u64)],
) -> String {
    let mut o = Map::new();
    o.insert("niveau".into(), niveau.into());
    o.insert("module".into(), "agent".into());
    o.insert("agent".into(), agent.into());
    o.insert("mission".into(), mission.into());
    o.insert("message".into(), message.into());
    for (nom, n) in compteurs {
        o.insert((*nom).into(), (*n).into());
    }
    Value::Object(o).to_string()
}

pub fn info(
    agent: &'static str,
    mission: &str,
    message: &'static str,
    compteurs: &[(&'static str, u64)],
) {
    println!("{}", ligne("info", agent, mission, message, compteurs));
}

pub fn erreur(
    agent: &'static str,
    mission: &str,
    message: &'static str,
    compteurs: &[(&'static str, u64)],
) {
    println!("{}", ligne("erreur", agent, mission, message, compteurs));
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn une_ligne_json_complete() {
        let l = ligne(
            "info",
            "revue",
            "m-1",
            "mission finie",
            &[("appels_modele", 3)],
        );
        let v: Value = serde_json::from_str(&l).unwrap();
        assert_eq!(v["niveau"], "info");
        assert_eq!(v["module"], "agent");
        assert_eq!(v["agent"], "revue");
        assert_eq!(v["mission"], "m-1");
        assert_eq!(v["message"], "mission finie");
        assert_eq!(v["appels_modele"], 3);
        assert!(!l.contains('\n'));
    }

    #[test]
    fn identifiant_echappe() {
        let l = ligne("erreur", "a", "m\"\n{", "x", &[]);
        let v: Value = serde_json::from_str(&l).unwrap();
        assert_eq!(v["mission"], "m\"\n{");
    }
}
