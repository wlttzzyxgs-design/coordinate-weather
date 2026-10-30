# Coordinate Weather Skill

[中文](#中文) | [English](#english)

一个零第三方依赖的 Agent Skill：输入经纬度，自动从兼容的天气数据服务获取当前天气、未来 3 天逐小时预报和每日摘要。支持普通天气与风电天气两套预设。

## 中文

### 功能

- 输入 WGS84 纬度、经度。
- 获取当前天气、逐小时预报和每日摘要。
- `general` 预设：温度、体感温度、湿度、降水、云量、10 米风速/风向和阵风。
- `wind` 预设：额外提供 80/100/120 米风速和风向，并计算风切变、高风速时段。
- 自动使用坐标所在地时区。
- 中文/英文输出，以及 Markdown、JSON 或两者同时输出。
- 免费接口默认可用；配置商业 API Key 后自动切换商业接口。
- 仅使用 Python 3.10+ 标准库，无需安装依赖。

### 安装

克隆仓库后，把 Skill 目录复制到 Codex Skills 目录。

Windows PowerShell：

```powershell
git clone https://github.com/wlttzzyxgs-design/coordinate-weather.git
Copy-Item -Recurse `
  .\coordinate-weather\skills\coordinate-weather `
  "$HOME\.codex\skills\coordinate-weather"
```

macOS / Linux：

```bash
git clone https://github.com/wlttzzyxgs-design/coordinate-weather.git
cp -R coordinate-weather/skills/coordinate-weather \
  "${CODEX_HOME:-$HOME/.codex}/skills/coordinate-weather"
```

兼容 Agent Skills 的宿主可直接安装：

```text
skills/coordinate-weather
```

### 使用

在 Agent 中：

```text
$coordinate-weather 获取 26.881144,103.881832 的天气预报
```

直接运行 CLI：

```bash
python skills/coordinate-weather/scripts/get_weather.py \
  --latitude 26.881144 \
  --longitude 103.881832
```

风电预设：

```bash
python skills/coordinate-weather/scripts/get_weather.py \
  --latitude 26.881144 \
  --longitude 103.881832 \
  --preset wind \
  --format both
```

英文 JSON：

```bash
python skills/coordinate-weather/scripts/get_weather.py \
  --latitude 51.5074 \
  --longitude -0.1278 \
  --lang en \
  --format json
```

完整参数：

```text
--latitude FLOAT        WGS84 latitude, -90..90
--longitude FLOAT       WGS84 longitude, -180..180
--preset                general | wind
--days                  1..16, default 3
--format                markdown | json | both
--api-mode              auto | free | customer
--lang                  zh-CN | en
--timezone              default auto
--json-out PATH         write normalized JSON to a file
```

### 免费与商业 API

- 免费模式无需 API Key。
- 商业模式需要配置 `WEATHER_API_KEY`，并切换到商业端点。

配置商业 Key：

Windows PowerShell：

```powershell
$env:WEATHER_API_KEY = "your-key"
```

macOS / Linux：

```bash
export WEATHER_API_KEY="your-key"
```

`--api-mode auto` 在存在 `WEATHER_API_KEY` 时自动使用商业接口。免费接口仅适用于非商业用途；公司生产、交易或对外服务应按相应的商业许可处理。

### 输出

JSON 顶层字段固定为：

```text
location
provider
period
preset
current
hourly
daily
summary
attribution
```

默认单位：摄氏度、米/秒、毫米。

### 数据许可

天气数据由 [Open-Meteo.com](https://open-meteo.com/) 提供，数据许可为 [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/)。

### 开发与测试

```bash
python -m unittest discover \
  -s skills/coordinate-weather/tests \
  -v
```

CI 在 Python 3.10 和 3.12 上运行相同测试。

## English

A dependency-free Agent Skill that accepts a coordinate pair and retrieves current weather, a 3-day hourly forecast, and daily summaries from a compatible weather data service.

### Features

- Current, hourly and daily weather data.
- `general` preset for everyday weather.
- `wind` preset with 80/100/120 m wind, gusts and logarithmic wind shear.
- Coordinate-based automatic timezone.
- Chinese or English Markdown/JSON output.
- Free endpoint by default; optional commercial endpoint through `WEATHER_API_KEY`.
- Python 3.10+ standard library only.

### Run

```bash
python skills/coordinate-weather/scripts/get_weather.py \
  --latitude 51.5074 \
  --longitude -0.1278 \
  --lang en \
  --format both
```

### Commercial API

```bash
export WEATHER_API_KEY="your-key"
```

With `--api-mode auto`, the skill switches to the customer endpoint whenever the key is present. The free endpoint is intended for non-commercial use.

### Data Licence

Weather data by [Open-Meteo.com](https://open-meteo.com/), licensed under [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

## License

The source code in this repository is licensed under the MIT License.
