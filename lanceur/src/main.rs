use std::sync::Arc;

use bollard::Docker;
use lanceur::api::{Etat, routeur};
use lanceur::config::Config;

fn arret(message: String) -> ! {
    eprintln!("{message}");
    std::process::exit(1)
}

#[tokio::main]
async fn main() {
    let cfg =
        Config::depuis_env().unwrap_or_else(|e| arret(format!("configuration invalide : {e}")));
    let docker = Docker::connect_with_defaults()
        .unwrap_or_else(|e| arret(format!("Docker injoignable : {e}")))
        .negotiate_version()
        .await
        .unwrap_or_else(|e| arret(format!("Docker injoignable : {e}")));
    // Sous l'API 1.45, `VolumeOptions.Subpath` serait ignoré : tout le volume serait monté.
    let v = docker.client_version();
    if (v.major_version, v.minor_version) < (1, 45) {
        arret(format!(
            "Docker Engine 26 ou plus requis (API {}.{} < 1.45)",
            v.major_version, v.minor_version
        ));
    }
    let ecoute = tokio::net::TcpListener::bind("0.0.0.0:8080")
        .await
        .unwrap_or_else(|e| arret(format!("écoute impossible sur 0.0.0.0:8080 : {e}")));
    let app = routeur(Arc::new(Etat {
        cfg,
        moteur: docker,
    }));
    if let Err(e) = axum::serve(ecoute, app).await {
        arret(format!("serveur arrêté : {e}"));
    }
}
