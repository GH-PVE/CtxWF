import json
import logging
import re
from typing import Any, Optional

from da_agent.agent.action import Action, ViewTable, ReadTextFile, Answer, CodeTaskExecutor, SQLTaskExecutor, \
    Decompress
from da_agent.agent.models import call_llm
from da_agent.agent.prompts import ACTION_REASONING_PROMPT, FILE_INFO_PRE_RETRIEVAL
from da_agent.envs.da_agent import DsAgentEnv

MAX_OBSERVATION_LENGTH = 2000
TIME_OUT_ACTION = 600

logger = logging.getLogger("da_agent")


class DsAgent:
    def __init__(
            self,
            model="QWEN/QWEN2.5-72B-Instruct",
            max_tokens=1500,
            top_p=0.9,
            temperature=0.5,
            max_memory_length=10,
            max_steps=15,
    ):

        self.model = model
        self.max_tokens = max_tokens
        self.top_p = top_p
        self.temperature = temperature
        self.max_memory_length = max_memory_length
        self.max_steps = max_steps

        self.env_max_steps = max_steps
        self.total_tokens = 0
        self.instruction = ""
        self.files_info = ""
        self.action_history = ""
        self.action_history_to_nl = ""
        self.action_space = ""
        self.retrieve_action_space = ""
        self.apis = ""

        self.thoughts = []
        self.responses = []
        self.actions = []
        self.observations = []
        self.action_history_record = []
        self.env = None
        self.codes = []
        self._AVAILABLE_ACTION_CLASSES = [ViewTable, ReadTextFile, CodeTaskExecutor, SQLTaskExecutor, Decompress, Answer]
        self._RETRIEVAL_ACTION_CLASSES = [ViewTable, ReadTextFile]

    def set_env_and_task(self, env: DsAgentEnv):
        self.env_max_steps = self.max_steps
        self.env = env
        self.total_tokens = 0
        self.thoughts = []
        self.responses = []
        self.actions = []
        self.observations = []
        self.codes = []
        self.action_history_record = []
        self.instruction = self.env.task_config['instruction']
        self.files_info = self.env.get_env_dit_tree()
        self.action_history = ""
        self.action_history_to_nl = ""
        self.action_space = "".join([action_cls.get_action_description() for action_cls in self._AVAILABLE_ACTION_CLASSES])
        self.retrieve_action_space = "".join([action_cls.get_action_description() for action_cls in self._RETRIEVAL_ACTION_CLASSES])
        self.apis = ""

    def pre_process(self):
        status = False
        retry_count = 0
        while not status:
            prompt = FILE_INFO_PRE_RETRIEVAL\
                .replace("{retrieval_action_space}", self.retrieve_action_space)\
                .replace("{files_info}", self.files_info)\
                .replace("{current_task}", self.instruction)
            status, response = self._call_llm(prompt)
            if not status:
                raise Exception(f"Failed to call LLM, response: {response}")
            res_json_str = re.search(r'```json\n(.*?)\n```', response, flags=re.DOTALL)
            if res_json_str:
                res_json = json.loads(res_json_str.group(1).strip())
                thought = res_json.get("thought")
                actions = res_json.get("actions")
                for action in actions:
                    action_obj = self._parse_action_from_text(action)
                    if action_obj is not None:
                        obs, _ = self.env.step(action_obj)
                        # 过滤执行失败的action
                        if "error" in obs.lower():
                            continue
                        self.thoughts.append(thought)
                        self.responses.append(response)
                        self.actions.append(action_obj)
                        self.observations.append(obs)
                        self.codes.append(None)
                        self._add_message(obs, action_obj)
                    else:
                        status = False
                        retry_count += 1
                        if retry_count > 3:
                            raise Exception(f"Failed to parse action from response, action: {action}")
                        break

    def predict(self) -> tuple[Any, Optional[Action]]:
        """
        Predict the next action(s) based on the current observation.
        """

        assert len(self.observations) == len(self.actions) and len(self.actions) == len(self.thoughts) \
            , "The number of observations and actions should be the same."

        count = 0
        status = False
        while not status and count < 3:
            self.action_history = "\n".join([f'* Action{i+1}: {str(action)}\n* Observation{i+1}: \n```\n{obs}\n```' for i, (action, obs) in enumerate(self.action_history_record)])
            self.action_history_to_nl = "\n".join([f'{i+1}. {action.get_executed_action_description(obs)}' for i, (action, obs) in enumerate(self.action_history_record)])
            prompt = ACTION_REASONING_PROMPT.format(action_space=self.action_space, task=self.instruction, max_steps=self.env_max_steps, files_info=self.files_info, action_history=self.action_history)
            status, response = self._call_llm(prompt)
            if not status:
                # Todo 删除时只应该删除关于code的记录
                if response in ["context_length_exceeded", "rate_limit_exceeded", "max_tokens"]:
                    raise Exception(f"token max limit!")
                    # logger.warning(f"token max limit!")
                    # self.action_history_record = [self.action_history_record[0]] + self.action_history_record[3:]
                else:
                    raise Exception(f"Failed to call LLM, response: {response}")

            try:
                action = self.parse_action(response)
                thought = re.search(r'Thought:(.*?)Action', response, flags=re.DOTALL)
                if thought:
                    thought = thought.group(1).strip()
                else:
                    thought = response
            except ValueError as e:
                print("Failed to parse action from response", e)
                thought = None
                action = None

            if action is None:
                status = False
                count += 1
                if count >= 3:
                    raise Exception(f"Failed to parse action from response, response: {response}")
            else:
                self.thoughts.append(thought)
                self.responses.append(response)
                self.actions.append(action)

        return response, action

    def _call_llm(self, prompt: str):
        status, response = call_llm({
            "model": self.model,
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
            "max_tokens": self.max_tokens,
            "top_p": self.top_p,
            "temperature": self.temperature
        }, self)
        response = response.strip()
        return status, response

    def _add_message(self, observation: str, action: Action):
        # action_str = str(action)
        # if isinstance(action, CodeTaskExecutor):
        #     action_str += f"\n```python\n{action.codes_history[-1]}\n```"
        self.action_history_record.append([action, observation])
        # self.action_history_record = self.action_history_record[-self.max_memory_length:]


    def _parse_action_from_text(self, action_string: str) -> Action:
        output_action = None
        for action_cls in self._AVAILABLE_ACTION_CLASSES:
            action = action_cls.parse_action_from_text(action_string)
            if action is not None:
                output_action = action
                break
        if output_action is None:
            action_string = action_string.replace("\_", "_").replace("'''", "```")
            for action_cls in self._AVAILABLE_ACTION_CLASSES:
                action = action_cls.parse_action_from_text(action_string)
                if action is not None:
                    output_action = action
                    break
        return output_action

    def parse_action(self, output: str) -> Action:
        """ Parse action from text """
        if output is None or len(output) == 0:
            pass
        action_string = ""
        patterns = [r'["\']?Action["\']?:? (.*?)Observation', r'["\']?Action["\']?:? (.*?)Thought',
                    r'["\']?Action["\']?:? (.*?)$', r'^(.*?)Observation']

        for p in patterns:
            match = re.search(p, output, flags=re.DOTALL)
            if match:
                action_string = match.group(1).strip()
                break
        if action_string == "":
            action_string = output.strip()

        return self._parse_action_from_text(action_string)

    def run(self):
        assert self.env is not None, "Environment is not set."
        self.pre_process()

        result = ""
        done = False
        step_idx = len(self.actions)
        # obs = "You are in the folder now."
        retry_count = 0
        last_action = None
        repeat_action = False
        while not done and step_idx < self.env_max_steps:

            response, action = self.predict()
            if action is None:
                logger.info("Failed to parse action from response, try again.")
                retry_count += 1
                if retry_count > 3:
                    logger.info("Failed to parse action from response, stop.")
                    break
                obs = "Failed to parse action from your response, make sure you provide a valid action."
            else:
                logger.info("Step %d: %s", step_idx + 1, response)
                if last_action is not None and last_action == action:
                    if repeat_action:
                        return False, "ERROR: Repeated action"
                    else:
                        obs = "The action is the same as the last one, please provide a different action."
                        repeat_action = True
                else:
                    try:
                        obs, done = self.env.step(action)
                        logger.info("Observation: %s", obs)
                    except Exception as e:
                        logger.error(f"Failed to execute action: {action}, error: {e}")
                        break
                    last_action = action
                    repeat_action = False

            if action is not None:
                self.codes.append(action.codes_history)
            else:
                self.codes.append(None)
            self.observations.append(obs)

            # change the agent's state
            self.files_info = self.env.get_env_dit_tree()
            self._add_message(obs, action)
            if done:
                if isinstance(action, Answer):
                    result = action.output
                logger.info("The task is done.")
                break
            step_idx += 1

        return done, result

    def get_trajectory(self):
        trajectory = []
        for i in range(len(self.observations)):
            trajectory.append({
                "thought": self.thoughts[i],
                "action": str(self.actions[i]),
                "observation": self.observations[i],
                "code": self.codes[i],
                "response": self.responses[i]
            })
        trajectory_log = {
            "Task": self.instruction,
            "final_state": self.env.get_env_dit_tree(),
            "trajectory": trajectory
        }
        return trajectory_log

    def get_total_tokens(self):
        return self.total_tokens


if __name__ == "__main__":
    agent = DsAgent()
    response = """Bash(code=\"\"ls -a\"):\n\n(Note: I am using the 'ls -a' command to list all files, including hidden ones, in the working directory. This will help me ensure that I am in the correct directory and provide a reference for the file paths.\")"""
    import pdb

    pdb.set_trace()
    action = agent.parse_action(response)
    print(action)
