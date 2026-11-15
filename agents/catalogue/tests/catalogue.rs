use catalogue::NOMS;

#[test]
fn noms_egaux_a_agents_yaml() {
    let yaml = std::fs::read_to_string(concat!(env!("CARGO_MANIFEST_DIR"), "/../../agents.yaml"))
        .expect("agents.yaml");
    // clés de second niveau sous `agents:`, motif `^  ([a-z_]+):$`, sans dépendance YAML
    let dans_agents: Vec<&str> = yaml
        .lines()
        .skip_while(|l| *l != "agents:")
        .skip(1)
        // s'arrête à la première clé de premier niveau suivante
        .take_while(|l| l.is_empty() || l.starts_with(' ') || l.starts_with('#'))
        .filter_map(|l| {
            let nom = l.strip_prefix("  ")?.strip_suffix(':')?;
            (!nom.is_empty()
                && nom
                    .bytes()
                    .all(|b| b.is_ascii_lowercase() || b == b'_' || b == b'-'))
            .then_some(nom)
        })
        .collect();
    assert_eq!(dans_agents, NOMS);
}

#[test]
fn un_binaire_par_agent() {
    let dossier = concat!(env!("CARGO_MANIFEST_DIR"), "/src/bin");
    let mut fichiers: Vec<String> = std::fs::read_dir(dossier)
        .expect("src/bin")
        .map(|e| e.unwrap().file_name().into_string().unwrap())
        .collect();
    fichiers.sort();
    let mut attendus: Vec<String> = NOMS.iter().map(|n| format!("{n}.rs")).collect();
    attendus.sort();
    assert_eq!(fichiers, attendus);
    for nom in NOMS {
        let source = std::fs::read_to_string(format!("{dossier}/{nom}.rs")).unwrap();
        assert!(
            source.contains(&format!("principal(\"{nom}\")")),
            "src/bin/{nom}.rs doit appeler principal(\"{nom}\")"
        );
    }
}
