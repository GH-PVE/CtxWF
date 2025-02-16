import json
import logging
import os
import re
from typing import Optional

import docker

from da_agent.agent.models import call_llm
from da_agent.agent.prompts import READ_TEXT_FILE_PROMPT, CODE_TASK_PROMPT, SQL_TASK_PROMPT, DB_TABLES_PRE_RETRIEVAL
from da_agent.configs.python_action_template import VIEW_TABLE_TEMPLATE, SQL_TEMPLATE, DB_TABLES_TEMPLATE, \
    DB_TABLE_COLUMNS_TEMPLATE, SQL2DB_TEMPLATE
from da_agent.envs.utils import timeout

logger = logging.getLogger("spider.pycontroller")

DEFAULT_TIME_OUT = 60

class PythonController:
    def __init__(self, agent, container, work_dir="/workspace"):
        self.agent = agent
        self.container = container
        self.mnt_dir = [mount['Source'] for mount in container.attrs['Mounts']][0]
        self.work_dir = work_dir

    def _get_file(self, file_path: str):
        """
        Gets a file from the docker container.
        """
        real_file_path = os.path.join(self.mnt_dir, file_path.replace("/workspace/", ""))
        file_content = ""
        try:
            with open(real_file_path, 'r') as file:
                file_content = file.read()
        except FileNotFoundError:
            print("File not found:", file_path)
        except Exception as e:
            print("An error occurred:", str(e))
        return file_content

    def _file_exists(self, file_path):
        real_file_path = os.path.join(self.mnt_dir, file_path.replace("/workspace/", ""))
        return os.path.exists(real_file_path)

    def _execute_command(self, command: str):
        try:
            with timeout(DEFAULT_TIME_OUT, "Action execution time exceeded!"):
                cmd = ["bash", "-c", command]
                exit_code, output = self.container.exec_run(cmd, workdir=self.work_dir)
                ## can't create a new python environment in the container, eg. python3 -m venv /path/to/venv
                if "venv" in command:
                    return "Creating a new python environment is not allowed in the container. You can use 'pip install' to install the required packages."
                is_cd_flag = command.strip().startswith("cd ")
                if is_cd_flag:
                    changed = command[command.index("cd ") + 3:].strip()
                    if "&&" in changed:
                        changed = changed[:changed.index("&&")].strip()
                    self.work_dir = self.update_working_directory(self.work_dir, changed)
                    return f"The command to change directory to {self.work_dir} is executed successfully."

                return output.decode("utf-8", errors="ignore").strip()
        except TimeoutError as e:
            return str(e)

    def _execute_python_file(self, content: str):
        escaped_content = content.replace('"', '\\"').replace('`', '\\`').replace('$', '\\$')
        sandbox_path = "/tmp/sandbox.py"
        create_command = f'echo "{escaped_content}" > {sandbox_path} && PYTHONWARNINGS="ignore" python3 {sandbox_path}'
        return self._execute_command(create_command)

    def _call_llm(self, prompt: str):
        status, response = call_llm({
            "model": self.agent.model,
            "messages": [{"role": "user", "content": [{"type": "text", "text": prompt}]}],
            "max_tokens": self.agent.max_tokens,
            "top_p": self.agent.top_p,
            "temperature": self.agent.temperature
        }, self.agent)
        response = response.strip()
        return status, response

    def _sql_tables_retrieve(self, task_goal: str, tables: str) -> list:
        status = False
        retry_count = 0
        while not status:
            prompt = DB_TABLES_PRE_RETRIEVAL.replace("{current_task}", task_goal).replace("{tables}", tables)
            status, response = self._call_llm(prompt)
            try:
                res_json_str = re.search(r'```json\n(.*?)\n```', response, flags=re.DOTALL)
                res_json = json.loads(res_json_str.group(1).strip())
                thought = res_json.get("thought")
                tables = res_json.get("tables")
                return tables
            except Exception as e:
                retry_count += 1
                status = False
                if retry_count > 3:
                    raise Exception(f"Failed to generate sql from response: {task_goal}")

    def _sql_generate(self, task_goal: str, tables: str, table_columns: str, last_sql_info: str):
        status = False
        retry_count = 0
        while not status:
            prompt = SQL_TASK_PROMPT.replace("{files_info}", self.agent.files_info)\
                .replace("{task}", self.agent.instruction).replace("{current_task}", task_goal)\
                .replace("{action_history}", self.agent.action_history_to_nl)\
                .replace("{tables}", tables).replace("{table_columns}", table_columns)\
                .replace("{last_sql_info}", last_sql_info)
            status, response = self._call_llm(prompt)
            try:
                res_json_str = re.search(r'```json\n(.*?)\n```', response, flags=re.DOTALL)
                res_json = json.loads(res_json_str.group(1).strip())
                thought = res_json.get("thought")
                sql_command = res_json.get("sql_command")
                output = res_json.get("output")
                return thought, sql_command, output
            except Exception as e:
                if isinstance(e, json.JSONDecodeError):
                    last_sql_info += f"\nYou should respond in the format '```json\n{{\n\"thought\": \"\",\n\"sql_command\": \"\",\n\"output\": \"\"\n}}\n```'"
                retry_count += 1
                status = False
                if retry_count > 3:
                    raise Exception(f"Failed to generate sql from response: {task_goal}, {response}")

    def execute_code_task(self, task_goal: str):
        success = False
        last_code_info = ""
        obs = ""
        codes = []
        count = 0
        # todo 对于warning信息需要判断是否对任务结果有影响
        while not success and count < 5:
            print(f"Executing code task: count={count}")
            prompt = CODE_TASK_PROMPT.format(apis=self.agent.apis, task=self.agent.instruction, files_info=self.agent.files_info, current_task=task_goal,
                                             action_history=self.agent.action_history_to_nl, last_code_info=last_code_info)
            status, response = self._call_llm(prompt)
            code = ""

            if status:
                matches = re.findall(r'Code:.*?```python\s*(.*?)\s*```', response, flags=re.DOTALL)
                if matches:
                    code = matches[-1]
                    obs = self._execute_python_file(code)
                    success = "traceback (most recent call last)" not in obs.lower() and "error" not in obs.lower()
                else:
                    obs = "\nYou should provide executable code snippets in the format '```python```'"
                last_code_info = f'```python \n{code}\n```\nExecution Feedback: \n{obs}'
                codes.append({"code": code, "obs": obs, "success": success})
            else:
                success = False

            # if not success:
            #     error_pattern = re.compile(r'\w+Error: .*')
            #     obs = '\n'.join(error_pattern.findall(obs))
            count += 1

        # step = len(codes)
        # if step > 1:
        #     self.agent.env_max_steps -= step - 1
        if not success:
            obs = "The task is not completed successfully. Please get more information or execute a simpler code task."
        return obs, codes

    def execute_read_text_file(self, file_path: str, task_goal: str) -> str:
        if not self._file_exists(file_path):
            return f"Error: File not found: {file_path}"

        file_content = self._get_file(file_path)
        if len(file_content) < 2500:
            return file_content

        file_content = file_content[:10000]
        prompt = READ_TEXT_FILE_PROMPT.format(file_path=file_path, task_goal=task_goal, file_content=file_content)
        status, response = self._call_llm(prompt)
        observation = file_content
        if status:
            matches = re.findall(r'Content:.*?```Plain Text\s*(.*?)\s*```', response, flags=re.DOTALL)
            if matches:
                observation = matches[-1]

        return observation

    def execute_view_table(self, file_path: str) -> str:
        if not self._file_exists(file_path):
            return f"Error: File not found: {file_path}"

        file_content = self._get_file(file_path)
        if len(file_content) < 2500:
            return file_content

        script_content = VIEW_TABLE_TEMPLATE.replace("{file_path}", file_path)
        output = self._execute_python_file(script_content)
        return output

    def execute_sql_task(self, file_path, task_goal):
        if not self._file_exists(file_path):
            return f"Error: File not found: {file_path}"

        if file_path.endswith(".sql"):
            base = os.path.splitext(file_path)[0]
            sqlite_file_path = f"{base}.sqlite"
            script = SQL2DB_TEMPLATE.format(file_path=file_path, sqlite_file_path=sqlite_file_path)
            self._execute_python_file(script)
            file_path = sqlite_file_path

        if not file_path.endswith(".db") and not file_path.endswith(".sqlite") and not file_path.endswith(".sq"):
            return "Error: Invalid file format. The database file must be accessible and in a format compatible with SQLite (e.g., .sqlite, .db).", ""

        tables_script = DB_TABLES_TEMPLATE.format(file_path=file_path)
        tables_str = self._execute_python_file(tables_script)

        if tables_str == '[]':
            return f'No data found in the database file: {file_path}'

        filter_tables = self._sql_tables_retrieve(task_goal, tables_str)
        filter_tables = [table for table in filter_tables if table in tables_str]

        table_column_str = ""
        if len(filter_tables) > 0:
            table_columns_script = DB_TABLE_COLUMNS_TEMPLATE.replace("{file_path}", file_path).replace("{table_names}", str(filter_tables))
            table_column_str = self._execute_python_file(table_columns_script)

        codes = [tables_str, filter_tables]

        success = False
        last_sql_info = ""
        obs = ""
        count = 0
        while not success and count < 5:
            print(f"Executing SQL task: count={count}")
            thought, sql_command, output = self._sql_generate(task_goal, tables_str, table_column_str, last_sql_info)
            script_content = SQL_TEMPLATE.format(file_path=file_path, command=sql_command, output=output)
            obs = self._execute_python_file(script_content)

            success = "error" not in obs.lower()
            codes.append({"sql": sql_command, "obs": obs, "thought": thought, "success": success})
            last_sql_info = f"```SQL\n{sql_command}\n```\nFeedback: \n{obs}"
            count += 1

        # observation = observation.split("\n", 1)[1]
        # step = len(codes) - 2
        # if step > 1:
        #     self.agent.env_max_steps -= step - 1
        if not success:
            obs = "The task is not completed successfully. Please execute multiple simpler SQL tasks and print the information or save it to a temporary csv file."
        return obs, codes

    def execute_extract_archive(self, file_path: str) -> str:
        if not self._file_exists(file_path):
            return f"Error: File not found: {file_path}"

        file_name, file_extension = os.path.splitext(file_path)

        if file_extension == '.zip':
            command = f'unzip -o {file_path}'
        elif file_extension == '.tar':
            command = f'tar --overwrite -xvf {file_path}'
        elif file_extension == '.tar.gz':
            command = f'tar --overwrite -xzvf {file_path}'
        elif file_extension == '.gz':
            command = f'gunzip -f {file_path}'
        else:
            return "Error: Invalid archive format. The archive file must be in .zip, .tar, or .gz format."

        return self._execute_command(command)

    def update_working_directory(self, current: str, changed: Optional[str] = None) -> str:
        """ Resolves absolute path from the current working directory path and the argument of the `cd` command
        @args:
            current (str): the current working directory
            changed (Optional[str]): the changed working directory, argument of shell `cd` command
        @return:
            new_path (str): absolute path of the new working directory in the container
        """
        if not changed:
            return current
        if changed[0] == "/":
            current = ""

        path = []
        for segment in (current + "/" + changed).split("/"):
            if segment == "..":
                if path:
                    path.pop()
            elif segment and segment != ".":
                path.append(segment)
        new_path = "/" + "/".join(path)
        return new_path


if __name__ == '__main__':
    client = docker.from_env()
    container_name = "Qwen2.5-72B-Instruct-di-csv-033"
    container = client.containers.get(container_name)

    # from da_agent.agent.agents import DsAgent
    # agent = DsAgent(
    #     model="Qwen/Qwen2.5-72B-Instruct",
    #     max_tokens=2000,
    #     top_p=0.9,
    #     temperature=0.0
    # )
    # controller = PythonController(agent, container)
    # print(controller.execute_sql(file_path="northwind.db", command="SELECT name FROM sqlite_master WHERE type='table'", output="direct"))
