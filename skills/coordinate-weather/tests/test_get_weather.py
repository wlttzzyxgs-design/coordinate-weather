from __future__ import annotations

import io
import json
import math
import sys
import tempfile
import unittest
import urllib.error
from email.message import Message
from pathlib import Path
from unittest.mock import patch


SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import get_weather as weather  # noqa: E402


def fake_payload() -> dict:
    hours = [
        "2026-10-31T00:00",
        "2026-10-31T01:00",
        "2026-10-31T02:00",
    ]
    payload = {
        "latitude": 26.881144,
        "longitude": 103.881832,
        "elevation": 2400.0,
        "timezone": "Asia/Shanghai",
        "timezone_abbreviation": "CST",
        "utc_offset_seconds": 28800,
        "current_units": {"temperature_2m": "°C", "wind_speed_10m": "m/s"},
        "current": {
            "time": "2026-10-31T00:00",
            "temperature_2m": 8.2,
            "apparent_temperature": 7.1,
            "relative_humidity_2m": 73,
            "precipitation": 0.0,
            "weather_code": 1,
            "cloud_cover": 18,
            "wind_speed_10m": 4.5,
            "wind_gusts_10m": 6.2,
            "wind_direction_10m": 180,
        },
        "hourly": {
            "time": hours,
            "temperature_2m": [8.2, 8.0, 7.8],
            "apparent_temperature": [7.1, 6.9, 6.8],
            "relative_humidity_2m": [73, 74, 75],
            "precipitation_probability": [5, 8, 10],
            "precipitation": [0.0, 0.0, 0.1],
            "weather_code": [1, 2, 61],
            "cloud_cover": [18, 30, 65],
            "wind_speed_10m": [4.5, 5.2, 6.0],
            "wind_gusts_10m": [6.2, 7.5, 9.0],
            "wind_direction_10m": [180, 185, 190],
            "wind_speed_80m": [7.0, 8.0, 9.0],
            "wind_speed_100m": [18.0, 18.5, 19.0],
            "wind_speed_120m": [9.0, 10.0, 11.0],
            "wind_direction_80m": [190, 190, 190],
            "wind_direction_100m": [190, 190, 190],
            "wind_direction_120m": [190, 190, 190],
        },
        "daily": {
            "time": ["2026-10-31"],
            "weather_code": [2],
            "temperature_2m_max": [14.5],
            "temperature_2m_min": [6.2],
            "precipitation_sum": [0.1],
            "precipitation_probability_max": [10],
            "wind_speed_10m_max": [6.0],
            "wind_gusts_10m_max": [9.0],
            "wind_direction_10m_dominant": [188],
            "sunrise": ["2026-10-31T07:02"],
            "sunset": ["2026-10-31T18:16"],
        },
    }
    return payload


class ValidationTests(unittest.TestCase):
    def test_valid_coordinates(self) -> None:
        weather.validate_coordinates(-90, 180)

    def test_invalid_latitude(self) -> None:
        with self.assertRaises(weather.WeatherValidationError):
            weather.validate_coordinates(91, 0)

    def test_invalid_longitude(self) -> None:
        with self.assertRaises(weather.WeatherValidationError):
            weather.validate_coordinates(0, -181)

    def test_invalid_days(self) -> None:
        with self.assertRaises(weather.WeatherValidationError):
            weather.validate_days(0)
        with self.assertRaises(weather.WeatherValidationError):
            weather.validate_days(17)


class ApiModeTests(unittest.TestCase):
    def test_auto_uses_free_without_key(self) -> None:
        self.assertEqual(weather.resolve_api_mode("auto", {}), ("free", ""))

    def test_auto_uses_customer_with_key(self) -> None:
        self.assertEqual(
            weather.resolve_api_mode("auto", {"WEATHER_API_KEY": "secret"}),
            ("customer", "secret"),
        )

    def test_customer_requires_key(self) -> None:
        with self.assertRaises(weather.WeatherValidationError):
            weather.resolve_api_mode("customer", {})

    def test_request_url_contains_customer_key(self) -> None:
        url, metadata = weather.build_request(
            26.88,
            103.88,
            "general",
            3,
            "auto",
            "customer",
            "abc123",
        )
        self.assertIn("customer-api.open-meteo.com", url)
        self.assertIn("apikey=abc123", url)
        self.assertEqual(metadata["api_mode"], "customer")

    def test_key_is_redacted(self) -> None:
        message = weather.redact_secret(
            "request failed: https://customer-api.open-meteo.com/v1/forecast?apikey=abc123"
        )
        self.assertNotIn("abc123", message)
        self.assertIn("[REDACTED]", message)


class RequestTests(unittest.TestCase):
    class Response:
        def __init__(self, payload: dict) -> None:
            self.payload = payload

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self) -> bytes:
            return json.dumps(self.payload).encode("utf-8")

    def test_retries_transient_http_errors(self) -> None:
        headers = Message()
        errors = [
            urllib.error.HTTPError("https://example", 500, "fail", headers, None),
            urllib.error.HTTPError("https://example", 429, "limited", headers, None),
        ]
        calls = []

        def opener(request, timeout):
            calls.append(request.full_url)
            if errors:
                raise errors.pop(0)
            return self.Response({"ok": True})

        result = weather.request_json(
            "https://example",
            opener=opener,
            sleeper=lambda _delay: None,
        )
        self.assertEqual(result, {"ok": True})
        self.assertEqual(len(calls), 3)

    def test_missing_required_section_fails(self) -> None:
        payload = fake_payload()
        del payload["hourly"]
        with self.assertRaises(weather.WeatherDataError):
            weather.normalize_weather(
                payload,
                26.88,
                103.88,
                "general",
                3,
                "free",
                "zh-CN",
            )


class NormalizationTests(unittest.TestCase):
    def test_general_normalization(self) -> None:
        data = weather.normalize_weather(
            fake_payload(),
            26.881144,
            103.881832,
            "general",
            3,
            "free",
            "zh-CN",
        )
        self.assertEqual(data["preset"], "general")
        self.assertEqual(data["current"]["description"], "大部晴朗")
        self.assertEqual(data["summary"]["today_precipitation_sum_mm"], 0.1)
        self.assertNotIn("max_wind_100m_ms", data["summary"])
        self.assertEqual(data["attribution"]["text"].split(" (")[0], "Weather data by Open-Meteo.com")

    def test_wind_normalization_and_shear(self) -> None:
        data = weather.normalize_weather(
            fake_payload(),
            26.881144,
            103.881832,
            "wind",
            3,
            "free",
            "zh-CN",
        )
        expected = abs(math.log(9.0 / 7.0) / math.log(1.5))
        self.assertAlmostEqual(data["hourly"][0]["wind_shear"], expected, places=4)
        self.assertEqual(data["summary"]["max_wind_100m_ms"], 19.0)
        self.assertEqual(len(data["summary"]["high_wind_hours"]), 3)
        self.assertEqual(data["daily"][0]["wind_speed_100m_max"], 19.0)

    def test_english_description(self) -> None:
        self.assertEqual(weather.weather_description(61, "en"), "Slight rain")


class OutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.data = weather.normalize_weather(
            fake_payload(),
            26.881144,
            103.881832,
            "wind",
            3,
            "free",
            "zh-CN",
        )

    def test_markdown_output(self) -> None:
        markdown = weather.render_markdown(self.data, "zh-CN")
        self.assertIn("坐标天气预报", markdown)
        self.assertIn("风电风险摘要", markdown)
        self.assertIn("CC BY 4.0", markdown)

    def test_json_output_is_valid(self) -> None:
        text = weather.render_output(self.data, "json", "zh-CN")
        parsed = json.loads(text)
        self.assertEqual(parsed["location"]["timezone"], "Asia/Shanghai")

    def test_both_output_contains_markdown_and_json(self) -> None:
        text = weather.render_output(self.data, "both", "zh-CN")
        self.assertIn("## 结构化数据", text)
        self.assertIn("```json", text)

    def test_json_file_is_written(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "nested" / "weather.json"
            weather.write_json(output, self.data)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["preset"], "wind")


class MainTests(unittest.TestCase):
    def test_main_prints_json(self) -> None:
        stdout = io.StringIO()
        with patch.object(weather, "fetch_weather", return_value=weather.normalize_weather(
            fake_payload(),
            26.881144,
            103.881832,
            "general",
            3,
            "free",
            "zh-CN",
        )), patch.object(sys, "stdout", stdout):
            code = weather.main(
                [
                    "--latitude",
                    "26.881144",
                    "--longitude",
                    "103.881832",
                    "--format",
                    "json",
                ]
            )
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(stdout.getvalue())["preset"], "general")


if __name__ == "__main__":
    unittest.main()
