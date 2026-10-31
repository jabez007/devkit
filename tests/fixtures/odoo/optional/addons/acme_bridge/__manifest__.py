{
    "name": "Acme Optional Bridge",
    "depends": ["base", "external_connector"],
    "auto_install": ["external_connector"],
    "external_dependencies": {"python": ["imaginary_client>=1"], "bin": ["imaginary-tool"]},
}
