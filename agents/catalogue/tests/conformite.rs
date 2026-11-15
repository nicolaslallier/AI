use catalogue::{NOMS, tourner};

#[tokio::test]
async fn chaque_agent_passe_la_conformite() {
    for nom in NOMS {
        agent::conformite::verifier(nom, tourner(nom).unwrap()).await;
    }
}
