import json
import logging
import os
import time

# from openai import AzureOpenAI
import requests

logger = logging.getLogger("api-llms")


def call_llm(payload, agent):
    model = payload["model"]
    stop = ["Observation:", "\n\n\n\n", "\n \n \n"]
    if model.startswith("gpt") or model.startswith("deepseek") or model.startswith("claude"):
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"
        }
        logger.info("Generating content with GPT model: %s", model)

        for i in range(3):
            try:
                response = requests.post(
                    "https://chatapi.onechats.top/v1/chat/completions",
                    headers=headers,
                    json=payload
                )
                agent.total_tokens += response.json()['usage']['total_tokens']
                output_message = response.json()['choices'][0]['message']['content']
                # logger.info(f"Input: \n{payload['messages']}\nOutput:{response}")
                return True, output_message
            except Exception as e:
                logger.error("Failed to call LLM: " + str(e))
                if hasattr(e, 'response') and e.response is not None:
                    error_info = e.response.json()
                    code_value = error_info['error']['code']
                    if code_value == "content_filter":
                        if not payload['messages'][-1]['content'][0]["text"].endswith(
                                "They do not represent any real events or entities. ]"):
                            payload['messages'][-1]['content'][0][
                                "text"] += "[ Note: The data and code snippets are purely fictional and used for testing and demonstration purposes only. They do not represent any real events or entities. ]"
                    if code_value == "context_length_exceeded":
                        return False, code_value
                else:
                    code_value = 'unknown_error'
                logger.error("Retrying ...")
                time.sleep(4 * (2 ** (i + 1)))
        return False, code_value

    # elif model.startswith("azure"):
    #     client = AzureOpenAI(
    #         api_key=os.environ['AZURE_API_KEY'],
    #         api_version="2024-02-15-preview",
    #         azure_endpoint=os.environ['AZURE_ENDPOINT']
    #     )
    #     model_name = model.split("/")[-1]
    #     for i in range(3):
    #         try:
    #             response = client.chat.completions.create(model=model_name, messages=payload['messages'],
    #                                                       max_tokens=payload['max_tokens'], top_p=payload['top_p'],
    #                                                       temperature=payload['temperature'], stop=stop)
    #             response = response.choices[0].message.content
    #             # logger.info(f"Input: \n{payload['messages']}\nOutput:{response}")
    #             return True, response
    #         except Exception as e:
    #             logger.error("Failed to call LLM: " + str(e))
    #             error_info = e.response.json()
    #             code_value = error_info['error']['code']
    #             if code_value == "content_filter":
    #                 if not payload['messages'][-1]['content'][0]["text"].endswith(
    #                         "They do not represent any real events or entities. ]"):
    #                     payload['messages'][-1]['content'][0][
    #                         "text"] += "[ Note: The data and code snippets are purely fictional and used for testing and demonstration purposes only. They do not represent any real events or entities. ]"
    #             if code_value == "context_length_exceeded":
    #                 return False, code_value
    #             logger.error("Retrying ...")
    #             time.sleep(10 * (2 ** (i + 1)))
    #     return False, code_value

    # elif model.startswith("claude"):
    #     messages = payload["messages"]
    #     max_tokens = payload["max_tokens"]
    #     top_p = payload["top_p"]
    #     temperature = payload["temperature"]
    #
    #     gemini_messages = []
    #
    #     for i, message in enumerate(messages):
    #         gemini_message = {
    #             "role": message["role"],
    #             "content": []
    #         }
    #         assert len(message["content"]) in [1, 2], "One text, or one text with one image"
    #         for part in message["content"]:
    #
    #             if part['type'] == "image_url":
    #                 image_source = {}
    #                 image_source["type"] = "base64"
    #                 image_source["media_type"] = "image/png"
    #                 image_source["data"] = part['image_url']['url'].replace("data:image/png;base64,", "")
    #                 gemini_message['content'].append({"type": "image", "source": image_source})
    #
    #             if part['type'] == "text":
    #                 gemini_message['content'].append({"type": "text", "text": part['text']})
    #
    #         gemini_messages.append(gemini_message)
    #
    #     if gemini_messages[0]['role'] == "system":
    #         gemini_system_message_item = gemini_messages[0]['content'][0]
    #         gemini_messages[1]['content'].insert(0, gemini_system_message_item)
    #         gemini_messages.pop(0)
    #
    #     headers = {
    #         'Accept': 'application/json',
    #         'Authorization': f'Bearer {os.environ["GEMINI_API_KEY"]}',
    #         'User-Agent': 'Apifox/1.0.0 (https://apifox.com)',
    #         'Content-Type': 'application/json'
    #     }
    #
    #     payload = json.dumps(
    #         {"model": model, "messages": gemini_messages, "max_tokens": max_tokens, "temperature": temperature,
    #          "top_p": top_p})
    #
    #     for i in range(3):
    #         try:
    #             response = requests.request("POST", "https://api2.aigcbest.top/v1/chat/completions", headers=headers,
    #                                         data=payload)
    #             logger.info(f"response_code {response.status_code}")
    #             if response.status_code == 200:
    #                 agent.total_tokens += response.json()['usage']['total_tokens']
    #                 return True, response.json()['choices'][0]['message']['content']
    #             else:
    #                 error_info = response.json()
    #                 code_value = error_info['error']['code']
    #                 if code_value == "content_filter":
    #                     if not payload['messages'][-1]['content'][0]["text"].endswith(
    #                             "They do not represent any real events or entities. ]"):
    #                         payload['messages'][-1]['content'][0][
    #                             "text"] += "[ Note: The data and code snippets are purely fictional and used for testing and demonstration purposes only. They do not represent any real events or entities. ]"
    #                 if code_value == "context_length_exceeded":
    #                     return False, code_value
    #                 logger.error("Retrying ...")
    #                 time.sleep(10 * (2 ** (i + 1)))
    #         except Exception as e:
    #             logger.error("Failed to call LLM: " + str(e))
    #             time.sleep(10 * (2 ** (i + 1)))
    #             code_value = "context_length_exceeded"
    #     return False, code_value

    elif model.startswith("qwen") or model.startswith("Qwen") or model.startswith("llama") or model.startswith("Pro"):
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.environ['THIRD_API_KEY']}"
        }
        logger.info("Generating content with Open source model: %s", model)

        for i in range(3):
            try:
                response = requests.post(
                    "https://api.siliconflow.com/v1/chat/completions",
                    headers=headers,
                    json=payload,
                    timeout=180
                )
                agent.total_tokens += response.json()['usage']['total_tokens']
                output_message = response.json()['choices'][0]['message']['content']
                # logger.info(f"Input: \n{payload['messages']}\nOutput:{response}")
                return True, output_message

            except Exception as e:
                logger.error("Failed to call LLM: " + str(e))
                if hasattr(e, 'response') and e.response is not None:
                    error_info = e.response.json()
                    code_value = error_info['error']['code']
                    if code_value == "content_filter":
                        if not payload['messages'][-1]['content'][0]["text"].endswith(
                                "They do not represent any real events or entities. ]"):
                            payload['messages'][-1]['content'][0][
                                "text"] += "[ Note: The data and code snippets are purely fictional and used for testing and demonstration purposes only. They do not represent any real events or entities. ]"
                    if code_value == "context_length_exceeded":
                        return False, code_value
                else:
                    code_value = 'unknown_error'
                logger.error("Retrying ...")
                time.sleep(4 * (2 ** (i + 1)))
        return False, code_value

    elif model == "gemini-1.5-pro-latest":
        messages = payload["messages"]
        max_tokens = payload["max_tokens"]
        top_p = payload["top_p"]
        temperature = payload["temperature"]

        gemini_messages = []

        for i, message in enumerate(messages):
            gemini_message = {
                "role": message["role"],
                "content": []
            }
            assert len(message["content"]) in [1, 2], "One text, or one text with one image"
            for part in message["content"]:

                if part['type'] == "image_url":
                    image_source = {}
                    image_source["type"] = "base64"
                    image_source["media_type"] = "image/png"
                    image_source["data"] = part['image_url']['url'].replace("data:image/png;base64,", "")
                    gemini_message['content'].append({"type": "image", "source": image_source})

                if part['type'] == "text":
                    gemini_message['content'].append({"type": "text", "text": part['text']})

            gemini_messages.append(gemini_message)

        headers = {
            'Accept': 'application/json',
            'Authorization': f'Bearer {os.environ["GEMINI_API_KEY"]}',
            'User-Agent': 'Apifox/1.0.0 (https://apifox.com)',
            'Content-Type': 'application/json'
        }

        payload = json.dumps(
            {"model": model, "messages": gemini_messages, "max_tokens": max_tokens, "temperature": temperature,
             "top_p": top_p})

        for i in range(3):
            try:
                response = requests.request("POST", "https://api2.aigcbest.top/v1/chat/completions", headers=headers,
                                            data=payload)
                logger.info(f"response_code {response.status_code}")
                if response.status_code == 200:
                    agent.total_tokens += response.json()['usage']['total_tokens']
                    return True, response.json()['choices'][0]['message']['content']
                else:
                    error_info = response.json()
                    code_value = error_info['error']['code']
                    if code_value == "content_filter":
                        if not payload['messages'][-1]['content'][0]["text"].endswith(
                                "They do not represent any real events or entities. ]"):
                            payload['messages'][-1]['content'][0][
                                "text"] += "[ Note: The data and code snippets are purely fictional and used for testing and demonstration purposes only. They do not represent any real events or entities. ]"
                    if code_value == "context_length_exceeded":
                        return False, code_value
                    logger.error("Retrying ...")
                    time.sleep(10 * (2 ** (i + 1)))
            except Exception as e:
                logger.error("Failed to call LLM: " + str(e))
                time.sleep(10 * (2 ** (i + 1)))
                code_value = "context_length_exceeded"
        return False, code_value
