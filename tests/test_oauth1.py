"""OAuth 1.0a signing against the published reference example."""
from __future__ import annotations

from hermes_x_bookmarks import oauth1


def test_signature_matches_the_oauth_core_reference_example():
    # OAuth Core 1.0 Appendix A.5 (photos.example.net), the classic HMAC-SHA1 test vector.
    url = "http://photos.example.net/photos?file=vacation.jpg&size=original"
    params = {
        "oauth_consumer_key": "dpf43f3p2l4k3l03",
        "oauth_token": "nnch734d00sl2jdk",
        "oauth_signature_method": "HMAC-SHA1",
        "oauth_timestamp": "1191242096",
        "oauth_nonce": "kllo9940pd9333jh",
        "oauth_version": "1.0",
    }
    assert oauth1.base_string("GET", url, [("file", "vacation.jpg"), ("size", "original"),
                                           *params.items()]) == (
        "GET&http%3A%2F%2Fphotos.example.net%2Fphotos&file%3Dvacation.jpg%26"
        "oauth_consumer_key%3Ddpf43f3p2l4k3l03%26oauth_nonce%3Dkllo9940pd9333jh%26"
        "oauth_signature_method%3DHMAC-SHA1%26oauth_timestamp%3D1191242096%26"
        "oauth_token%3Dnnch734d00sl2jdk%26oauth_version%3D1.0%26size%3Doriginal")
    sig = oauth1.signature("GET", url, params, "kd94hf93k423kf44", "pfkkdhi9sl3r4s00")
    assert sig == "tR3+Ty81lMeYAr/Fid0kMTYa/WM="


def test_commas_in_x_field_lists_are_signed_as_percent_encoded():
    base = oauth1.base_string("GET", "https://api.x.com/2/tweets?ids=1,2",
                              [("ids", "1,2")])
    assert "ids%3D1%252C2" in base  # comma -> %2C, then encoded again in the base string


def test_header_is_deterministic_with_fixed_nonce_and_clock():
    header = oauth1.authorization_header(
        "GET", "https://api.x.com/2/users/me", consumer_key="ck", consumer_secret="cs",
        token="tk", token_secret="ts", nonce=lambda: "n", clock=lambda: 1800000000)
    assert header.startswith('OAuth oauth_consumer_key="ck", oauth_nonce="n"')
    assert 'oauth_timestamp="1800000000"' in header and "oauth_signature=" in header
