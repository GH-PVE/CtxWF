import re
from abc import ABC
from dataclasses import dataclass, field
from typing import Optional, Any


def remove_quote(text: str) -> str:
    """ 
    If the text is wrapped by a pair of quote symbols, remove them.
    In the middle of the text, the same quote symbol should remove the '/' escape character.
    """
    for quote in ['"', "'", "`"]:
        if text.startswith(quote) and text.endswith(quote):
            text = text[1:-1]
            text = text.replace(f"\\{quote}", quote)
            break
    return text.strip()


@dataclass
class Action(ABC):
    action_type: str = field(
        repr=False,
        metadata={"help": 'type of action, e.g. "view_table", "read_text_file", "code_task_executor", "answer"'}
    )

    @classmethod
    def get_action_description(cls) -> str:
        return """
Action: action format
Description: detailed definition of this action type.
Usage: example cases
Observation: the observation space of this action type.
"""

    def get_executed_action_description(self, obs: str) -> str:
        return f"You have executed `{self.action_type}` action. The contents are as follows:\n```\n{obs}\n```"

    @classmethod
    def parse_action_from_text(cls, text: str) -> Optional[Any]:
        raise NotImplementedError


@dataclass
class ViewTable(Action):
    action_type: str = field(
        default="view_table",
        init=False,
        repr=False,
        metadata={"help": 'type of action, c.f., "view_table"'}
    )

    codes_history: list = field(
        default=None,
    )

    file_path: str = field(
        default=None,
        metadata={"help": 'path to the table file'}
    )

    @classmethod
    def get_action_description(cls) -> str:
        return """
## ViewTable Action 
* Signature: ViewTable(file_path="path/to/table_file") 
* Description: This action will get the table structure and a portion of the data of the table file located at 'file_path'.
* Constraints: 
  - The table file must be accessible and in a tabular data format (e.g., .csv, .tsv). 
* Example: ViewTable(file_path="info.csv")
"""

    def get_executed_action_description(self, obs: str) -> str:
        return f"You have get the table structure and a portion of the data of from the `{self.file_path}` file. The contents are as follows:\n```\n{obs}\n```"

    @classmethod
    def parse_action_from_text(cls, text: str) -> Optional[Action]:
        matches = re.findall(r'ViewTable\(file_path=(.*?)\)', text, flags=re.DOTALL)
        if matches:
            file_path = matches[-1]
            return cls(file_path=remove_quote(file_path))
        return None

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}(file_path="{self.file_path}")'


@dataclass
class ReadTextFile(Action):
    action_type: str = field(
        default="read_text_file",
        init=False,
        repr=False,
        metadata={"help": 'type of action, c.f., "read_text_file"'}
    )

    codes_history: list = field(
        default=None,
    )

    file_path: str = field(
        default=None,
        metadata={"help": 'path to the text file'}
    )

    task_goal: str = field(
        default=None,
        metadata={"help": 'description of the information you want to obtain in the file'}
    )

    @classmethod
    def get_action_description(cls) -> str:
        return """
## ReadTextFile Action 
* Signature: ReadTextFile(file_path="path/to/file", task_goal="a detailed description of the information you want to obtain in the file") 
* Description: This action will read the file and extract a **relevant section of text** from the file specified by 'file_path' based on the 'task_goal'. 
* Example: ReadTextFile(file_path="info.txt", task_goal="the description for 'money'")
"""

    def get_executed_action_description(self, obs: str) -> str:
        return f"You have acquired a relevant section of text from the `{self.file_path}` file to know `{self.task_goal}`. The contents are as follows:\n```\n{obs}\n```"

    @classmethod
    def parse_action_from_text(cls, text: str) -> Optional[Action]:
        matches = re.findall(r'ReadTextFile\(file_path=(.*?), task_goal=(.*?)\)', text, flags=re.DOTALL)
        if matches:
            file_path, task_goal = (item.strip() for item in matches[-1])
            return cls(file_path=remove_quote(file_path), task_goal=remove_quote(task_goal))
        return None

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}(file_path="{self.file_path}", task_goal="{self.task_goal}")'


@dataclass
class CodeTaskExecutor(Action):
    action_type: str = field(
        default="code_task_executor",
        init=False,
        repr=False,
        metadata={"help": 'type of action, c.f., "code_task_executor"'}
    )

    task_goal: Optional[str] = field(
        metadata={"help": 'goal of the task'}
    )

    codes_history: list = field(
        default=None,
        metadata={"help": 'executable code snippets'}
    )

    @classmethod
    def get_action_description(cls) -> str:
        return """
## CodeTaskExecutor Action 
* Signature: CodeTaskExecutor(task_goal="task_goal")
* Description: This action will generate and execute the program code to achieve the task goal.
* Example: CodeTaskExecutor(task_goal="Print the 'Hello, world!' string.") 
"""

    def get_executed_action_description(self, obs: str) -> str:
        action_desc = f"You have generated and executed the program code to achieve the task goal `{self.task_goal}`."
        if self.codes_history and len(self.codes_history) > 0 and self.codes_history[-1]['success']:
            final_code = self.codes_history[-1]['code']
            action_desc += f"\nCode:\n```python\n{final_code}\n```"
        action_desc += f"\nFeedback:\n```\n{obs}\n```"
        return action_desc

    @classmethod
    def parse_action_from_text(cls, text: str) -> Optional[Action]:
        matches = re.findall(r'CodeTaskExecutor\(task_goal=(.*)\)', text, flags=re.DOTALL)
        if matches:
            task_goal = matches[-1]
            return cls(task_goal=remove_quote(task_goal))
        return None

    def set_code_history(self, codes: list):
        self.codes_history = codes

    def __repr__(self) -> str:
        action_str = f'{self.__class__.__name__}(task_goal="{self.task_goal}")'
        if self.codes_history and len(self.codes_history) > 0 and self.codes_history[-1]['success']:
            action_str += f"\n```python\n{self.codes_history[-1]['code']}\n```"
        return action_str


@dataclass
class SQLTaskExecutor(Action):
    action_type: str = field(
        default="sql_task_executor",
        init=False,
        repr=False,
        metadata={"help": 'type of action, c.f., "sql_task_executor"'}
    )

    codes_history: list = field(
        default=None
    )

    file_path: str = field(
        default=None,
        metadata={"help": 'path to the database file'}
    )

    task_goal: str = field(
        default=None,
        metadata={"help": 'SQL command to achieve the task goal'}
    )

    @classmethod
    def get_action_description(cls) -> str:
        return """
## SQLTaskExecutor Action 
* Signature: SQLTaskExecutor(file_path="path/to/database_file", task_goal="a detailed description of the task") 
* Description: This action will generate and execute the SQL commands on the specified database file to achieve the task goal.
* Constraints: 
  - The database file must be accessible and in a format compatible with SQLite (e.g., .sqlite, .db). 
* Example: SQLTaskExecutor(file_path="data.sqlite", task_goal="Calculate the average of the quantities.") 
"""

    def get_executed_action_description(self, obs: str) -> str:
        action_desc = f"You have generated and executed the SQL command on the `{self.file_path}` file to achieve the task goal `{self.task_goal}`."
        if self.codes_history and len(self.codes_history) > 2 and self.codes_history[-1]['success']:
            final_sql = self.codes_history[-1]['sql']
            action_desc += f"\nSQL command:\n```SQL\n{final_sql}\n```"
        action_desc += f"\nFeedback:\n```\n{obs}\n```"
        return action_desc

    @classmethod
    def parse_action_from_text(cls, text: str) -> Optional[Action]:
        matches = re.findall(r'SQLTaskExecutor\(file_path=(.*?), task_goal=(.*?)\)', text, flags=re.DOTALL)
        if matches:
            file_path, task_goal = (item.strip() for item in matches[-1])
            return cls(file_path=remove_quote(file_path), task_goal=remove_quote(task_goal))
        return None

    def set_code_history(self, sql_task_history: list):
        self.codes_history = sql_task_history

    def __repr__(self) -> str:
        action_str = f'{self.__class__.__name__}(file_path="{self.file_path}", task_goal="{self.task_goal}")'
        if self.codes_history and len(self.codes_history) > 2 and self.codes_history[-1]['success']:
            action_str += f"\n```SQL\n{self.codes_history[-1]['sql']}\n```"
        return action_str


@dataclass
class Decompress(Action):
    action_type: str = field(
        default="decompress_command",
        init=False,
        repr=False,
        metadata={
            "help": "type of action, c.f., 'decompress_command'"}
    )

    file_path: str = field(
        default=None,
        metadata={"help": 'path to the compressed file'}
    )

    codes_history: list = field(
        default=None
    )

    @classmethod
    def get_action_description(cls) -> str:
        return """
## Decompress Action 
* Signature: Decompress(file_path="path/to/compressed_file")
* Description: This action will extract the contents of the compressed file located at 'file_path'. It supports .zip and .tar and .gz formats.
* Examples: 
  - Example1: Decompress(file_path="data.zip")
  - Example2: Decompress(file_path="data.gz")
"""

    def get_executed_action_description(self, obs: str) -> str:
        return f"You have extracted the contents of the compressed file `{self.file_path}`. The feedback are as follows: ```\n{obs}\n```"

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}(file_path="{self.file_path}")'

    @classmethod
    def parse_action_from_text(cls, text: str) -> Optional[Action]:
        matches = re.findall(r'Decompress\(file_path=(.*)\)', text, flags=re.DOTALL)
        if matches:
            file_path = matches[-1]
            return cls(file_path=remove_quote(file_path))
        return None


@dataclass
class Answer(Action):
    action_type: str = field(
        default="answer",
        init=False,
        repr=False,
        metadata={
            "help": "answer action representing the task is finished, or you think it is impossible for you to complete the task"}
    )

    output: Optional[str] = field(
        default=None,
        metadata={"help": "answer to the task or output file path or 'FAIL', if exists"}
    )

    codes_history: list = field(
        default=None
    )

    @classmethod
    def get_action_description(cls) -> str:
        return """
## Answer Action 
* Signature: Answer(output="literal_answer_or_output_path") 
* Description: This action denotes the completion of the entire task and returns the final answer or the output file/folder path. Make sure the output file is located in the initial workspace directory. 
* Examples: 
  - Example1: Answer(output="New York") 
  - Example2: Answer(output="result.csv") 
  - Example3: Answer(output="FAIL")
"""

    def get_executed_action_description(self, obs: str) -> str:
        return f"Successful!"

    def __repr__(self) -> str:
        return f'{self.__class__.__name__}(output="{self.output}")'

    @classmethod
    def parse_action_from_text(cls, text: str) -> Optional[Action]:
        matches = re.findall(r'Answer\(output=(.*)\)', text, flags=re.DOTALL)
        if matches:
            output = matches[-1]
            return cls(output=remove_quote(output))
        return None
