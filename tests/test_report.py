from gpudoctor.report import redact


def r(text, hostname="sneha-desktop", username="sneha", home="/home/sneha"):
    return redact(text, hostname=hostname, username=username, home=home)


def test_redacts_identity():
    text = "host sneha-desktop user sneha path /home/sneha/.cache file /home/sneha"
    assert r(text) == "host <hostname> user <user> path <home>/.cache file <home>"


def test_does_not_mangle_substrings():
    # "sneha" inside another word is left alone.
    assert r("snehalata and nvidia") == "snehalata and nvidia"


def test_skips_short_and_root_names():
    assert r("pi root /root", hostname="pi", username="root", home="/root") == "pi root /root"
    assert r("x", hostname=None, username=None, home=None) == "x"


def test_redacts_uuids_serials_macs():
    text = (
        "GPU-1a2b3c4d-1111-2222-3333-444455556666 root=UUID=0f0e0d0c-aaaa-bbbb-cccc-111122223333 "
        "Serial Number : 1324021012345 serial=ABC123 ether 3c:52:82:aa:bb:cc"
    )
    out = r(text)
    assert "GPU-<uuid>" in out
    assert "root=UUID=<uuid>" in out
    assert "Serial Number : <serial>" in out
    assert "serial=<serial>" in out
    assert "<mac>" in out
    for secret in ("1a2b3c4d", "0f0e0d0c", "1324021012345", "ABC123", "3c:52"):
        assert secret not in out
