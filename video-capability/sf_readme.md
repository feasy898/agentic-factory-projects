English | [简体中文](./README-CN.md)

## Project Description

This project allows users to input a story theme and generates a story video using a large language model. The video includes AI-generated images, story content, audio, and subtitles.

The backend technology stack consists of Python + FastAPI framework, while the frontend is built with React + Ant Design + Vite.

## Video Demonstration

<table>
<thead>
<tr>
<th align="center"><g-emoji class="g-emoji" alias="arrow_forward">▶️</g-emoji> The Story of the Rabbit and the Little Fox</th>
<th align="center"><g-emoji class="g-emoji" alias="arrow_forward">▶️</g-emoji> The Story of the Big Gray Wolf and the Little White Rabbit</th>
</tr>
</thead>
<tbody>
<tr>
<td align="center"><video src="https://github.com/user-attachments/assets/e1893b9c-83ed-420c-a29a-1f5f878117c4"></video></td>
<td align="center"><video src="https://github.com/user-attachments/assets/8868e1b5-a931-4d25-9762-859a4c32d4f4"></video></td>
</tr>
</tbody>
</table>

## Interface Screenshot

![](backend/examples/screenshot/usage.jpg)

## Usage Instructions

### 1. Download the project

```
git clone https://github.com/alecm20/story-flicks.git
```

### 2. Set model information

```
# First, switch to the project’s backend directory first.
cd backend
cp .env.example .env


text_provider = "openai"  # Provider of the text generation model. Currently supports openai, aliyun, deepseek, ollama, and siliconflow.  
                          # Aliyun documentation: https://www.aliyun.com/product/bailian

image_provider = "aliyun"  # Provider of the image generation model. Currently supports openai, aliyun, and siliconflow.

openai_base_url="https://api.openai.com/v1" # The base URL for OpenAI

aliyun_base_url="https://dashscope.aliyuncs.com/compatible-mode/v1" # The base URL for Aliyun

deepseek_base_url="https://api.deepseek.com/v1" # The base URL for DeepSeek

ollama_base_url="http://localhost:11434/v1" # The base URL for Ollama

siliconflow_base_url="https://api.siliconflow.cn/v1" # The base URL for SiliconFlow

openai_api_key= # The API key for OpenAI, only one key needs to be provided

aliyun_api_key= # The API key for Aliyun Bailian, only one key needs to be provided

deepseek_api_key= # The API key for DeepSeek, currently only text generation is supported

ollama_api_key= # If you need to use it, please set api_key to “ollama”. Currently, this API key only supports text generation and cannot be used with models that have too few parameters. It is recommended to use qwen2.5:14b or a larger model.

siliconflow_api_key= # The API key for SiliconFlow, siliconflow's text model currently only supports large models compatible with the OpenAI format, such as Qwen/Qwen2.5-7B-Instruct. The image model has only been tested with black-forest-labs/FLUX.1-dev.


text_llm_model=gpt-4o # If text_provider is set to openai, only OpenAI models can be used, such as gpt-4o. If aliyun is selected, Aliyun models like qwen-plus or qwen-max can be used. Ollama models cannot be used with models that have too few parameters. It is recommended to use qwen2.5:14b or a larger model.

image_llm_model=flux-dev # If image_provider is set to openai, only OpenAI models can be used, such as dall-e-3. If aliyun is selected, Aliyun models like flux-dev are recommended, which are currently available for free trial. More details: https://help.aliyun.com/zh/model-studio/getting-started/models#a1a9f05a675m4.
```

### 3. Start the project

#### 3.1 Manual Startup

**Start the backend project**

```
# First, switch to the project root directory
cd backend
conda create -n story-flicks python=3.10 # Using conda, other virtual environments can also be used
conda activate story-flicks
pip install -r requirements.txt
uvicorn main:app --reload
```

If the project starts successfully, the following output will appear:

```
INFO:     Uvicorn running on http://127.0.0.1:8000 (Press CTRL+C to quit)
INFO:     Started reloader process [78259] using StatReload
INFO:     Started server process [78261]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

**Start the frontend project**

```
# First, switch to the project root directory
cd frontend
npm install
npm run dev

# After successful startup, open: http://localhost:5173/
```

When successfully started, the following output will appear:

```
  VITE v6.0.7  ready in 199 ms

  ➜  Local:   http://localhost:5173/
  ➜  Network: use --host to expose
  ➜  press h + enter to show help
```

#### 3.2 Start via Docker

In the project root directory, run:

```
docker-compose up --build
```

Once successful, open the frontend project at: http://localhost:5173/

### 4. Get started

Based on the fields in the interface, select the text generation model provider, image generation model provider, text model, image model, video language, voice, story theme, and story segments. Then click “Generate” to create the video. The number of images generated will correspond to the number of segments specified, with one image per segment. The more segments you set, the longer it will take to generate the video. Once the generation is successful, the video will be displayed on the frontend page.
