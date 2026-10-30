#!/usr/bin/env python3
"""Fetch current and forecast weather from a coordinate-based weather service."""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable


__version__ = "0.1.1"

FREE_ENDPOINT = "https://api.open-meteo.com/v1/forecast"
CUSTOMER_ENDPOINT = "https://customer-api.open-meteo.com/v1/forecast"
ATTRIBUTION_URL = "https://open-meteo.com/"
LICENCE_URL = "https://open-meteo.com/en/licence"
USER_AGENT = f"coordinate-weather/{__version__}"
MAX_DAYS = 16
MAX_ATTEMPTS = 3
HIGH_WIND_MS = 17.2
HIGH_SHEAR = 0.25

GENERAL_CURRENT = [
    "temperature_2m",
    "apparent_temperature",
    "relative_humidity_2m",
    "precipitation",
    "weather_code",
    "cloud_cover",
    "wind_speed_10m",
    "wind_gusts_10m",
    "wind_direction_10m",
]

GENERAL_HOURLY = [
    "temperature_2m",
    "apparent_temperature",
    "relative_humidity_2m",
    "precipitation_probability",
    "precipitation",
    "weather_code",
    "cloud_cover",
    "wind_speed_10m",
    "wind_gusts_10m",
    "wind_direction_10m",
]

WIND_HOURLY = [
    "wind_speed_80m",
    "wind_speed_100m",
    "wind_speed_120m",
    "wind_direction_80m",
    "wind_direction_100m",
    "wind_direction_120m",
]

DAILY_VARIABLES = [
    "weather_code",
    "temperature_2m_max",
    "temperature_2m_min",
    "precipitation_sum",
    "precipitation_probability_max",
    "wind_speed_10m_max",
    "wind_gusts_10m_max",
    "wind_direction_10m_dominant",
    "sunrise",
    "sunset",
]

WMO_CODES = {
    0: ("晴", "Clear sky"),
    1: ("大部晴朗", "Mainly clear"),
    2: ("局部多云", "Partly cloudy"),
    3: ("阴", "Overcast"),
    45: ("有雾", "Fog"),
    48: ("雾凇", "Depositing rime fog"),
    51: ("小毛毛雨", "Light drizzle"),
    53: ("中等毛毛雨", "Moderate drizzle"),
    55: ("强毛毛雨", "Dense drizzle"),
    56: ("轻度冻毛毛雨", "Light freezing drizzle"),
    57: ("强冻毛毛雨", "Dense freezing drizzle"),
    61: ("小雨", "Slight rain"),
    63: ("中雨", "Moderate rain"),
    65: ("大雨", "Heavy rain"),
    66: ("轻度冻雨", "Light freezing rain"),
    67: ("强冻雨", "Heavy freezing rain"),
    71: ("小雪", "Slight snowfall"),
    73: ("中雪", "Moderate snowfall"),
    75: ("大雪", "Heavy snowfall"),
    77: ("雪粒", "Snow grains"),
    80: ("小阵雨", "Slight rain showers"),
    81: ("中等阵雨", "Moderate rain showers"),
    82: ("强阵雨", "Violent rain showers"),
    85: ("小阵雪", "Slight snow showers"),
    86: ("强阵雪", "Heavy snow showers"),
    95: ("雷暴", "Thunderstorm"),
    96: ("雷暴伴小冰雹", "Thunderstorm with slight hail"),
    99: ("雷暴伴大冰雹", "Thunderstorm with heavy hail"),
}


class WeatherError(Exception):
    """Base class for user-facing weather errors."""


class WeatherValidationError(WeatherError):
    """Invalid coordinate or command input."""


class WeatherAPIError(WeatherError):
    """Remote API failed or returned unusable data."""


class WeatherDataError(WeatherError):
    """The API response is missing required weather sections or fields."""


def weather_description(code: Any, lang: str = "zh-CN") -> str:
    """Translate a WMO weather code into a short description."""
    try:
        labels = WMO_CODES.get(int(code))
    except (TypeError, ValueError):
        labels = None
    if not labels:
        return "未知天气" if lang == "zh-CN" else "Unknown weather"
    return labels[0] if lang == "zh-CN" else labels[1]


def validate_coordinates(latitude: float, longitude: float) -> None:
    """Validate WGS84 latitude and longitude ranges."""
    if not math.isfinite(latitude) or not -90 <= latitude <= 90:
        raise WeatherValidationError("latitude must be between -90 and 90")
    if not math.isfinite(longitude) or not -180 <= longitude <= 180:
        raise WeatherValidationError("longitude must be between -180 and 180")


def validate_days(days: int) -> None:
    """Validate weather forecast day count."""
    if not 1 <= days <= MAX_DAYS:
        raise WeatherValidationError(f"days must be between 1 and {MAX_DAYS}")


def resolve_api_mode(requested: str, env: dict[str, str] | None = None) -> tuple[str, str]:
    """Resolve API mode and key without exposing the key in output."""
    values = env if env is not None else os.environ
    api_key = str(values.get("WEATHER_API_KEY", "")).strip()
    if requested == "free":
        return "free", ""
    if requested == "customer":
        if not api_key:
            raise WeatherValidationError(
                "WEATHER_API_KEY is required when --api-mode customer is used"
            )
        return "customer", api_key
    if api_key:
        return "customer", api_key
    return "free", ""


def build_request(
    latitude: float,
    longitude: float,
    preset: str,
    days: int,
    timezone_name: str,
    api_mode: str,
    api_key: str,
) -> tuple[str, dict[str, str]]:
    """Build the forecast URL and non-secret request metadata."""
    hourly = GENERAL_HOURLY + (WIND_HOURLY if preset == "wind" else [])
    params = {
        "latitude": f"{latitude:.6f}",
        "longitude": f"{longitude:.6f}",
        "current": ",".join(GENERAL_CURRENT),
        "hourly": ",".join(hourly),
        "daily": ",".join(DAILY_VARIABLES),
        "forecast_days": str(days),
        "timezone": timezone_name,
        "temperature_unit": "celsius",
        "wind_speed_unit": "ms",
        "precipitation_unit": "mm",
        "timeformat": "iso8601",
    }
    if api_mode == "customer":
        params["apikey"] = api_key
        endpoint = CUSTOMER_ENDPOINT
    else:
        endpoint = FREE_ENDPOINT
    return endpoint + "?" + urllib.parse.urlencode(params), {
        "resource": endpoint,
        "api_mode": api_mode,
    }


def redact_secret(text: str) -> str:
    """Remove any apikey value from an error or diagnostic string."""
    return str(text).replace("apikey=" + _extract_api_key(str(text)), "apikey=[REDACTED]")


def _extract_api_key(text: str) -> str:
    query = urllib.parse.urlsplit(text).query if "?" in text else text
    return str(urllib.parse.parse_qs(query).get("apikey", [""])[0])


def _retry_after_seconds(headers: Any, default: float) -> float:
    try:
        value = float(headers.get("Retry-After", ""))
        return min(max(value, 0.0), 10.0)
    except (TypeError, ValueError):
        return default


def request_json(
    url: str,
    timeout: int = 30,
    attempts: int = MAX_ATTEMPTS,
    opener: Callable[..., Any] | None = None,
    sleeper: Callable[[float], None] | None = None,
) -> Any:
    """Request JSON with bounded retries for throttling and transient failures."""
    open_url = opener or urllib.request.urlopen
    sleep = sleeper or time.sleep
    last_error = "request failed"
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with open_url(request, timeout=timeout) as response:
                raw = response.read().decode("utf-8")
            return json.loads(raw)
        except urllib.error.HTTPError as exc:
            last_error = redact_secret(f"HTTP {exc.code}: {exc.reason}")
            retryable = exc.code == 429 or 500 <= exc.code <= 599
            if not retryable or attempt + 1 >= attempts:
                break
            delay = _retry_after_seconds(exc.headers, 1.5 * (attempt + 1))
            sleep(delay)
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            last_error = redact_secret(f"network error: {exc}")
            if attempt + 1 >= attempts:
                break
            sleep(1.5 * (attempt + 1))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise WeatherAPIError(redact_secret(f"invalid JSON response: {exc}")) from exc
    raise WeatherAPIError(last_error)


def _section(payload: dict[str, Any], name: str) -> dict[str, Any]:
    value = payload.get(name)
    if not isinstance(value, dict):
        raise WeatherDataError(f"response is missing object: {name}")
    return value


def _times(section: dict[str, Any], name: str) -> list[str]:
    times = section.get("time")
    if not isinstance(times, list) or not times:
        raise WeatherDataError(f"response is missing {name}.time")
    return [str(value) for value in times]


def _series(section: dict[str, Any], key: str, size: int, required: bool = False) -> list[Any]:
    values = section.get(key)
    if not isinstance(values, list):
        if required:
            raise WeatherDataError(f"response is missing required field: {key}")
        return [None] * size
    if len(values) < size:
        values = values + [None] * (size - len(values))
    return values[:size]


def wind_shear_index(speed_80m: Any, speed_120m: Any) -> float | None:
    """Calculate the logarithmic wind shear exponent between 80 m and 120 m."""
    try:
        low = float(speed_80m)
        high = float(speed_120m)
    except (TypeError, ValueError):
        return None
    if low <= 0 or high <= 0:
        return None
    return round(abs(math.log(high / low) / math.log(1.5)), 4)


def normalize_weather(
    payload: dict[str, Any],
    latitude: float,
    longitude: float,
    preset: str,
    days: int,
    api_mode: str,
    lang: str,
) -> dict[str, Any]:
    """Normalize weather response into the skill's stable JSON contract."""
    current_source = _section(payload, "current")
    hourly_source = _section(payload, "hourly")
    daily_source = _section(payload, "daily")
    hourly_times = _times(hourly_source, "hourly")
    daily_times = _times(daily_source, "daily")

    current_time = current_source.get("time")
    current_code = current_source.get("weather_code")
    if not current_time or current_code is None:
        raise WeatherDataError("response is missing current.time or current.weather_code")
    if hourly_source.get("temperature_2m") is None:
        raise WeatherDataError("response is missing hourly.temperature_2m")
    if daily_source.get("temperature_2m_max") is None:
        raise WeatherDataError("response is missing daily.temperature_2m_max")

    current = {
        "time": str(current_time),
        "weather_code": current_code,
        "description": weather_description(current_code, lang),
        **{
            key: current_source.get(key)
            for key in GENERAL_CURRENT
            if key != "weather_code"
        },
        "units": payload.get("current_units") or {},
    }

    hourly_fields = GENERAL_HOURLY + (WIND_HOURLY if preset == "wind" else [])
    hourly_series = {
        key: _series(
            hourly_source,
            key,
            len(hourly_times),
            required=key in {"temperature_2m", "wind_speed_10m"},
        )
        for key in hourly_fields
    }
    hourly = []
    for index, valid_at in enumerate(hourly_times):
        row = {"time": valid_at}
        for key in hourly_fields:
            row[key] = hourly_series[key][index]
        row["description"] = weather_description(row.get("weather_code"), lang)
        if preset == "wind":
            row["wind_shear"] = wind_shear_index(
                row.get("wind_speed_80m"),
                row.get("wind_speed_120m"),
            )
        hourly.append(row)

    daily_series = {
        key: _series(daily_source, key, len(daily_times))
        for key in DAILY_VARIABLES
    }
    daily = []
    for index, forecast_date in enumerate(daily_times):
        row = {"date": forecast_date}
        for key in DAILY_VARIABLES:
            row[key] = daily_series[key][index]
        row["description"] = weather_description(row.get("weather_code"), lang)
        if preset == "wind":
            day_rows = [
                item
                for item in hourly
                if str(item["time"]).startswith(forecast_date)
            ]
            speed_100m = _finite_values(
                item.get("wind_speed_100m") for item in day_rows
            )
            gusts = _finite_values(
                item.get("wind_gusts_10m") for item in day_rows
            )
            shear = _finite_values(item.get("wind_shear") for item in day_rows)
            row["wind_speed_100m_max"] = max(speed_100m) if speed_100m else None
            row["wind_gust_max"] = max(gusts) if gusts else None
            row["wind_shear_max"] = max(shear) if shear else None
        daily.append(row)

    summary = _build_summary(current, hourly, daily, preset, lang)
    generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    return {
        "location": {
            "latitude": payload.get("latitude", latitude),
            "longitude": payload.get("longitude", longitude),
            "elevation": payload.get("elevation"),
            "timezone": payload.get("timezone"),
            "timezone_abbreviation": payload.get("timezone_abbreviation"),
            "utc_offset_seconds": payload.get("utc_offset_seconds"),
        },
        "provider": {
            "name": "Weather Data Service",
            "api_mode": api_mode,
            "requested_model": "best_match",
            "parameters": {
                "temperature_unit": "celsius",
                "wind_speed_unit": "ms",
                "precipitation_unit": "mm",
                "timezone": payload.get("timezone", "auto"),
            },
            "generated_at": generated_at,
        },
        "period": {
            "days": days,
            "start_date": daily_times[0],
            "end_date": daily_times[-1],
        },
        "preset": preset,
        "current": current,
        "hourly": hourly,
        "daily": daily,
        "summary": summary,
        "attribution": {
            "text": "Weather data by Open-Meteo.com (CC BY 4.0)",
            "url": ATTRIBUTION_URL,
            "licence_url": LICENCE_URL,
        },
    }


def _finite_values(values: Any) -> list[float]:
    output = []
    for value in values:
        try:
            number = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(number):
            output.append(number)
    return output


def _build_summary(
    current: dict[str, Any],
    hourly: list[dict[str, Any]],
    daily: list[dict[str, Any]],
    preset: str,
    lang: str,
) -> dict[str, Any]:
    today = daily[0] if daily else {}
    summary = {
        "current_description": current["description"],
        "today_date": today.get("date"),
        "today_temperature_max_c": today.get("temperature_2m_max"),
        "today_temperature_min_c": today.get("temperature_2m_min"),
        "today_precipitation_sum_mm": today.get("precipitation_sum"),
        "today_precipitation_probability_max_pct": today.get(
            "precipitation_probability_max"
        ),
        "max_wind_10m_ms": _max_field(hourly, "wind_speed_10m"),
        "max_gust_10m_ms": _max_field(hourly, "wind_gusts_10m"),
    }
    if preset == "wind":
        summary.update(
            {
                "max_wind_100m_ms": _max_field(hourly, "wind_speed_100m"),
                "high_wind_threshold_ms": HIGH_WIND_MS,
                "high_shear_threshold": HIGH_SHEAR,
                "high_wind_hours": [
                    {
                        "time": row["time"],
                        "wind_speed_100m_ms": row["wind_speed_100m"],
                    }
                    for row in hourly
                    if _number(row.get("wind_speed_100m")) is not None
                    and float(row["wind_speed_100m"]) >= HIGH_WIND_MS
                ],
                "high_shear_hours": [
                    {
                        "time": row["time"],
                        "wind_shear": row["wind_shear"],
                    }
                    for row in hourly
                    if _number(row.get("wind_shear")) is not None
                    and float(row["wind_shear"]) >= HIGH_SHEAR
                ],
            }
        )
    return summary


def _number(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _max_field(rows: list[dict[str, Any]], key: str) -> float | None:
    values = _finite_values(row.get(key) for row in rows)
    return max(values) if values else None


def _fmt(value: Any, digits: int = 1, suffix: str = "") -> str:
    number = _number(value)
    if number is None:
        return "—"
    return f"{number:.{digits}f}{suffix}"


def render_markdown(data: dict[str, Any], lang: str = "zh-CN") -> str:
    """Render a concise human-readable weather report."""
    location = data["location"]
    current = data["current"]
    summary = data["summary"]
    provider = data["provider"]
    daily = data["daily"]
    if lang == "zh-CN":
        lines = [
            "# 坐标天气预报",
            "",
            (
                f"**位置**：{location['latitude']}, {location['longitude']}  "
                f"**时区**：{location.get('timezone') or '未知'}  "
                f"**海拔**：{_fmt(location.get('elevation'), 1, ' m')}"
            ),
            (
                f"**数据源**：气象数据服务（{provider['api_mode']}）  "
                f"**获取时间**：{provider['generated_at']}"
            ),
            "",
            "## 当前天气",
            "",
            f"- 天气：**{current['description']}**",
            f"- 气温：**{_fmt(current.get('temperature_2m'), 1, ' ℃')}**，"
            f"体感 {_fmt(current.get('apparent_temperature'), 1, ' ℃')}",
            f"- 湿度：{_fmt(current.get('relative_humidity_2m'), 0, '%')}",
            f"- 风：{_fmt(current.get('wind_speed_10m'), 1, ' m/s')}，"
            f"阵风 {_fmt(current.get('wind_gusts_10m'), 1, ' m/s')}",
            "",
            f"## 未来 {data['period']['days']} 天",
            "",
            "| 日期 | 天气 | 最低/最高温 | 降水 | 最大风速 | 最大阵风 |",
            "|---|---|---:|---:|---:|---:|",
        ]
        for row in daily:
            lines.append(
                "| {date} | {weather} | {low} / {high} | {rain} | {wind} | {gust} |".format(
                    date=row["date"],
                    weather=row["description"],
                    low=_fmt(row.get("temperature_2m_min"), 1, " ℃"),
                    high=_fmt(row.get("temperature_2m_max"), 1, " ℃"),
                    rain=_fmt(row.get("precipitation_sum"), 1, " mm"),
                    wind=_fmt(row.get("wind_speed_10m_max"), 1, " m/s"),
                    gust=_fmt(row.get("wind_gusts_10m_max"), 1, " m/s"),
                )
            )
        if data["preset"] == "wind":
            lines.extend(
                [
                    "",
                    "## 风电风险摘要",
                    "",
                    f"- 100 米最大风速：**{_fmt(summary.get('max_wind_100m_ms'), 1, ' m/s')}**",
                    f"- 高风速时段（≥ {HIGH_WIND_MS:.1f} m/s）："
                    f"**{len(summary.get('high_wind_hours', []))} 小时**",
                    f"- 高风切变时段（≥ {HIGH_SHEAR:.2f}）："
                    f"**{len(summary.get('high_shear_hours', []))} 小时**",
                ]
            )
        lines.extend(
            [
                "",
                "## 数据说明",
                "",
                "- 时间采用坐标所在地自动时区；温度 ℃、风速 m/s、降水 mm。",
                "- 免费接口仅适用于非商业使用；商业部署应配置商业 API Key。",
                f"- 数据署名：[Open-Meteo.com]({ATTRIBUTION_URL})，数据许可 CC BY 4.0。",
            ]
        )
    else:
        lines = [
            "# Coordinate Weather Forecast",
            "",
            (
                f"**Location**: {location['latitude']}, {location['longitude']}  "
                f"**Timezone**: {location.get('timezone') or 'unknown'}  "
                f"**Elevation**: {_fmt(location.get('elevation'), 1, ' m')}"
            ),
            (
                f"**Provider**: Weather Data Service ({provider['api_mode']})  "
                f"**Generated**: {provider['generated_at']}"
            ),
            "",
            "## Current Weather",
            "",
            f"- Conditions: **{current['description']}**",
            f"- Temperature: **{_fmt(current.get('temperature_2m'), 1, ' °C')}**, "
            f"feels like {_fmt(current.get('apparent_temperature'), 1, ' °C')}",
            f"- Humidity: {_fmt(current.get('relative_humidity_2m'), 0, '%')}",
            f"- Wind: {_fmt(current.get('wind_speed_10m'), 1, ' m/s')}, "
            f"gusts {_fmt(current.get('wind_gusts_10m'), 1, ' m/s')}",
            "",
            f"## Next {data['period']['days']} Days",
            "",
            "| Date | Weather | Min/Max | Precipitation | Max wind | Max gust |",
            "|---|---|---:|---:|---:|---:|",
        ]
        for row in daily:
            lines.append(
                "| {date} | {weather} | {low} / {high} | {rain} | {wind} | {gust} |".format(
                    date=row["date"],
                    weather=row["description"],
                    low=_fmt(row.get("temperature_2m_min"), 1, " °C"),
                    high=_fmt(row.get("temperature_2m_max"), 1, " °C"),
                    rain=_fmt(row.get("precipitation_sum"), 1, " mm"),
                    wind=_fmt(row.get("wind_speed_10m_max"), 1, " m/s"),
                    gust=_fmt(row.get("wind_gusts_10m_max"), 1, " m/s"),
                )
            )
        if data["preset"] == "wind":
            lines.extend(
                [
                    "",
                    "## Wind-Energy Summary",
                    "",
                    f"- Maximum 100 m wind: **{_fmt(summary.get('max_wind_100m_ms'), 1, ' m/s')}**",
                    f"- High-wind hours (≥ {HIGH_WIND_MS:.1f} m/s): "
                    f"**{len(summary.get('high_wind_hours', []))}**",
                    f"- High-shear hours (≥ {HIGH_SHEAR:.2f}): "
                    f"**{len(summary.get('high_shear_hours', []))}**",
                ]
            )
        lines.extend(
            [
                "",
                "## Data Notes",
                "",
                "- Times use the coordinate's automatic timezone; units are °C, m/s and mm.",
                "- The free endpoint is for non-commercial use; commercial deployments need an API key.",
                f"- Data attribution: [Open-Meteo.com]({ATTRIBUTION_URL}), CC BY 4.0.",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def write_json(path: Path, data: dict[str, Any]) -> None:
    """Write normalized JSON atomically."""
    path = path.expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=path.parent,
        prefix=path.name + ".",
        suffix=".tmp",
        delete=False,
    )
    temp_name = Path(handle.name)
    try:
        with handle:
            json.dump(data, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
        os.replace(temp_name, path)
    except Exception:
        try:
            temp_name.unlink(missing_ok=True)
        except OSError:
            pass
        raise


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Fetch current and 3-day weather from a compatible weather service by coordinates."
    )
    parser.add_argument("--latitude", type=float, required=True)
    parser.add_argument("--longitude", type=float, required=True)
    parser.add_argument("--preset", choices=("general", "wind"), default="general")
    parser.add_argument("--days", type=int, default=3)
    parser.add_argument(
        "--format",
        choices=("markdown", "json", "both"),
        default="both",
    )
    parser.add_argument(
        "--api-mode",
        choices=("auto", "free", "customer"),
        default="auto",
    )
    parser.add_argument("--lang", choices=("zh-CN", "en"), default="zh-CN")
    parser.add_argument("--timezone", default="auto")
    parser.add_argument("--json-out", type=Path)
    parser.add_argument("--version", action="version", version=__version__)
    return parser


def fetch_weather(args: argparse.Namespace) -> dict[str, Any]:
    validate_coordinates(args.latitude, args.longitude)
    validate_days(args.days)
    if not str(args.timezone).strip():
        raise WeatherValidationError("timezone must not be empty")
    api_mode, api_key = resolve_api_mode(args.api_mode)
    url, _metadata = build_request(
        args.latitude,
        args.longitude,
        args.preset,
        args.days,
        args.timezone,
        api_mode,
        api_key,
    )
    payload = request_json(url)
    return normalize_weather(
        payload,
        args.latitude,
        args.longitude,
        args.preset,
        args.days,
        api_mode,
        args.lang,
    )


def render_output(data: dict[str, Any], output_format: str, lang: str) -> str:
    markdown = render_markdown(data, lang)
    json_text = json.dumps(data, ensure_ascii=False, indent=2)
    if output_format == "markdown":
        return markdown
    if output_format == "json":
        return json_text + "\n"
    heading = "## 结构化数据" if lang == "zh-CN" else "## Structured Data"
    return markdown + "\n" + heading + "\n\n```json\n" + json_text + "\n```\n"


def main(argv: list[str] | None = None) -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        data = fetch_weather(args)
        if args.json_out:
            try:
                write_json(args.json_out, data)
            except OSError as exc:
                raise WeatherError(f"cannot write JSON output: {exc}") from exc
        output = render_output(data, args.format, args.lang)
        if args.json_out and args.format == "both":
            json_heading = "## 结构化数据" if args.lang == "zh-CN" else "## Structured Data"
            output = output.split("\n" + json_heading, 1)[0].rstrip() + "\n"
        sys.stdout.write(output)
        return 0
    except WeatherValidationError as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        return 2
    except WeatherAPIError as exc:
        print(f"Weather API error: {exc}", file=sys.stderr)
        return 3
    except WeatherDataError as exc:
        print(f"Invalid weather data: {exc}", file=sys.stderr)
        return 4
    except WeatherError as exc:
        print(f"Weather error: {exc}", file=sys.stderr)
        return 5


if __name__ == "__main__":
    raise SystemExit(main())
