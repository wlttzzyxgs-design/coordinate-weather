---
name: coordinate-weather
description: Fetch current and 3-day hourly/daily weather from a compatible weather data service using latitude and longitude, with general or wind-energy presets and optional commercial API access.
---

# Coordinate Weather

Use this skill when the user supplies a WGS84 latitude/longitude and asks for current weather, a forecast, daily planning conditions, or wind-energy weather risk.

## Workflow

1. Confirm the pair is latitude, longitude. If the user gives an ambiguous pair, ask which value is latitude.
2. Use `general` for ordinary weather. Use `wind` when the user needs 80/100/120 m wind, gusts, wind shear, or wind-farm operations.
3. Run the bundled script from this skill directory.
4. Return the Chinese or English summary requested by the user. When structured data is useful, keep the JSON output or write it with `--json-out`.
5. Report API or missing-data failures directly. Never invent values.

## Command

```bash
python scripts/get_weather.py \
  --latitude 26.881144 \
  --longitude 103.881832 \
  --preset general \
  --days 3 \
  --format both \
  --lang zh-CN
```

Common options:

- `--preset general|wind`
- `--days 1..16` (default `3`)
- `--format markdown|json|both`
- `--lang zh-CN|en`
- `--timezone auto`
- `--api-mode auto|free|customer`
- `--json-out PATH`

## API Modes

- Default `auto` uses the free endpoint unless `WEATHER_API_KEY` is set.
- With `WEATHER_API_KEY`, `auto` switches to the customer endpoint.
- Never print, persist or commit the API key.
- Mention that the free endpoint is for non-commercial use; production business use needs an appropriate commercial licence.

## Data Rules

- The script requests metric units and the coordinate's automatic timezone.
- WMO weather codes are translated into human-readable descriptions.
- Wind shear is `abs(ln(v120/v80) / ln(1.5))`; values below zero wind speed are treated as unavailable.
- Include the Open-Meteo CC BY 4.0 attribution when presenting results.
- Do not add geocoding, historical weather, ensemble forecasts, batch coordinates or a web UI unless the skill is explicitly extended.
