from app.services.sbom_packages import extract_osv_packages, parse_purl


def test_parse_purl_maps_common_ecosystems() -> None:
    assert parse_purl("pkg:pypi/requests@2.32.0").ecosystem == "PyPI"
    assert parse_purl("pkg:npm/%40scope/widget@1.2.3").name == "@scope/widget"
    assert (
        parse_purl("pkg:maven/org.apache.commons/commons-lang3@3.12.0").name
        == "org.apache.commons:commons-lang3"
    )
    assert parse_purl("pkg:golang/github.com/acme/widget@v1.0.0").name == "github.com/acme/widget"


def test_extract_osv_packages_deduplicates_and_skips_unsupported_refs() -> None:
    response = {
        "sbom": {
            "packages": [
                {
                    "externalRefs": [
                        {"referenceType": "purl", "referenceLocator": "pkg:pypi/requests@2.32.0"},
                        {"referenceType": "purl", "referenceLocator": "pkg:pypi/requests@2.32.0"},
                    ]
                },
                {
                    "externalRefs": [
                        {"referenceType": "purl", "referenceLocator": "pkg:generic/acme/widget@1.0.0"},
                    ]
                },
            ]
        }
    }

    packages = extract_osv_packages(response)

    assert [(item.ecosystem, item.name, item.version) for item in packages] == [
        ("PyPI", "requests", "2.32.0")
    ]
