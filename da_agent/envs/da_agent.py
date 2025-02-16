import logging
import pathlib
import time
from typing import Any
from typing import Dict

import docker
from docker.client import DockerClient
from docker.errors import ImageNotFound
from docker.models.containers import Container

from da_agent import configs
from da_agent.agent.action import Action, ViewTable, ReadTextFile, Answer, CodeTaskExecutor, SQLTaskExecutor, \
    Decompress
from da_agent.controllers.python import PythonController
from da_agent.controllers.setup import SetupController
from da_agent.envs.utils import *

logger = logging.getLogger("da_agent.env")


# constants
START_UP_DELAY = 2 # start up delay for docker container
DEFAULT_TIME_OUT = 60 * 2 # default waiting time for each action
MAX_OBS_LENGTH = 3000
EMPTY_DATA_PATH = 'da_agent/data/empty' # an empty data directory
DEFAULT_IMAGE_DIR = 'da_agent/images' # default directory to store docker images
DEFAULT_WORK_DIR = '/workspace' # default working directory in the container
DEFAULT_MNT_DIR = 'da_agent/mnt' # default directory to copy and mount data path, also the output directory
TASK_FINISHED = "task_finished" # infos key
ACTION_EXEC = "action_executed" # infos key


class DsAgentEnv:
    def __init__(self, agent, task_config, env_config, source_dir, cache_dir, mnt_dir):
        super().__init__()
        self.task_config = task_config
        self.cache_dir_base = cache_dir
        self.container_name = env_config['init_args']['name']
        self.image_name = env_config['image_name']
        self.source_dir = source_dir
        self.mnt_dir = mnt_dir
        self.work_dir = DEFAULT_WORK_DIR
        self.kwargs = env_config['init_args']

        self._set_task_info(task_config)
        logger.info("Initializing...")
        self._construct_container()

        self.controller = PythonController(agent=agent, container=self.container, work_dir=self.work_dir)
        self.setup_controller = SetupController(container=self.container, cache_dir=self.cache_dir)

        logger.info("Setting up environment...")

        dir = os.path.join(self.source_dir, self.task_id)
        assert os.path.isdir(dir), f"Task directory {dir} does not exist."
        self.setup_controller.setup_cp_dir(dir)
        self.init_files_hash = self._get_env_files_hash()
        time.sleep(2)
        logger.info("Environment setup complete.")

    def _set_task_info(self, task_config: Dict[str, Any]):
        self.task_id: str = task_config['id']
        self.cache_dir: str = os.path.join(self.cache_dir_base, self.task_id)
        # os.makedirs(self.cache_dir, exist_ok=True)
        self.instruction = task_config["instruction"]
        self.post_process_func = task_config["post_process"] if "post_process" in task_config else []
        
    def close(self):
        self.container.stop()
        self.container.remove()
        logger.info(f"Container {self.container_name} stopped and removed.")
        
    def _construct_container(self):
        client = docker.from_env()
        container_name = self.container_name
        #### delete existing container
        try:
            container = client.containers.get(container_name)
            container.stop()
            container.remove()
            print(f"Container {container_name} stopped and removed.")
        except docker.errors.NotFound:
            pass
        except docker.errors.APIError as e:
            pass

        create_folder_if_not_exists(self.mnt_dir)
        src_dir = pathlib.Path(self.mnt_dir).absolute().__str__()
        delete_files_in_folder(self.mnt_dir)

        volumes = {src_dir: {'bind': self.work_dir, 'mode': 'rw'}}
        allowed_params = ['command', 'ports', 'restart_policy', 'entrypoint', 'hostname', 'domainname', 'name', 'user',
                          'mac_address', 'platform', 'network_mode', 'network_disabled', 'healthcheck', "environment"]
        kwargs = {k: self.kwargs[k] for k in self.kwargs if k in allowed_params}
        extra_params = {'detach': True, 'tty': True, 'stdout': True, 'stderr': True, 'stdin_open': True, **kwargs}

        try:
            client: DockerClient = docker.from_env()
            image = client.images.get(self.image_name)
            self.container: Container = client.containers.run(image=image, volumes=volumes, **extra_params)
        except ImageNotFound as e:
            dockerfile_path = os.path.join(DEFAULT_IMAGE_DIR, self.image_name)
            if os.path.exists(dockerfile_path):
                logger.info(f"Image {self.image_name} not found, try to build from dockerfile {dockerfile_path} ...")
                image = client.images.build(path=dockerfile_path, tag=self.image_name, rm=True)[0]
            else:
                logger.info(f"Image {self.image_name} not found, try to pull from Dockerhub ...")
                image = client.images.pull(self.image_name)[0]
            self.container: Container = client.containers.run(image=image, volumes=volumes, **extra_params)
        except Exception as e:
            logger.info(f"Failed to construct container from image {self.image_name} with error: {e}")
            raise e

        time.sleep(START_UP_DELAY)
        logger.info(
            f"Connected to container[name={self.container.name}, id={self.container.id}] from image {self.image_name} ...")

        return self.container

    def _get_env_files_hash(self) -> Dict[str, str]:
        """
        Returns:
            Dict[str, str]: a dictionary of the hash of the files in the
              environment
        """
        files_hash = {}
        for root, dirs, files in os.walk(self.mnt_dir):
            for f in files:
                file_path = os.path.join(root, f)
                files_hash[file_path] = calculate_sha256(file_path)
        return files_hash

    def post_process(self, trajectory):
        """
        Evaluate whether the task is successfully completed.
        """
        diff_files = self._find_diff_files_init(self.init_files_hash)

        num = 1
        for trajectory_item in trajectory:
            action_str = trajectory_item['action']
            if action_str.startswith("CodeTaskExecutor") and trajectory_item['code'] and len(trajectory_item['code']) > 0:
                final_code = trajectory_item['code'][-1]['code']
                final_success = trajectory_item['code'][-1]['success']
                if final_success:
                    with open(os.path.join(self.mnt_dir, f"sandbox{num}.py"), "w") as f:
                        f.write(final_code + "\n")
                    num += 1

        post_process_files = []
        errors = []
        for post_process_f in self.post_process_func:
            process_function = getattr(configs, post_process_f, None)
            post_files, error = process_function(self.mnt_dir, self.controller)
            post_files = post_files if isinstance(post_files, list) else list(post_files)
            post_process_files.extend(post_files)
            errors.append(error)

        return {**diff_files, "post_process_files": post_process_files, "error": errors}

    def _find_diff_files_init(self, init_file_dict)-> Dict:
        init_file_paths = init_file_dict.keys()
        added_files_list = []
        changed_files_list = []
        for root, dirs, files in os.walk(self.mnt_dir):
            for f in files:
                file_path = os.path.join(root, f)
                if file_path not in init_file_paths:
                    added_files_list.append(file_path)
                else:
                    if init_file_dict[file_path] != calculate_sha256(file_path):
                        changed_files_list.append(file_path)
        return {"added_files": added_files_list, "changed_files": changed_files_list}

    def _get_directory_tree(self, root_dir, prefix=""):
        tree = []
        contents = sorted(os.listdir(root_dir))
        pointers = ['├── '] * (len(contents) - 1) + ['└── ']

        for pointer, path in zip(pointers, contents):
            full_path = os.path.join(root_dir, path)
            tree.append(prefix + pointer + path)
            if os.path.isdir(full_path):
                extension = '│   ' if pointer == '├── ' else '    '
                tree.extend(self._get_directory_tree(full_path, prefix + extension))

        return tree

    def get_env_dit_tree(self):
        tree = self._get_directory_tree(self.mnt_dir)
        return ".\n" + "\n".join(tree)

    def step(self, action: Action):
        done = False
        if isinstance(action, ViewTable):
            observation = self.execute_view_table_action(action)
        elif isinstance(action, SQLTaskExecutor):
            observation = self.execute_sql_task_action(action)
        elif isinstance(action, ReadTextFile):
            observation = self.execute_read_text_file_action(action)
        elif isinstance(action, CodeTaskExecutor):
            observation = self.execute_code_task_action(action)
        elif isinstance(action, Decompress):
            observation = self.execute_extract_archive(action)
        elif isinstance(action, Answer):
            observation = "Terminate"
            done = True
        else:
            raise ValueError(f"Unrecognized action type {action.action_type} !")
        
        observation = self._handle_observation(observation)
        return observation, done
    
    def _handle_observation(self, observation):
        max_length = MAX_OBS_LENGTH  
        if len(observation) > max_length:
            truncated_observation = observation[:max_length] + "\n[Observation too long, truncated; Try other commands to get the left part.]"
            return truncated_observation
        return observation

    def execute_view_table_action(self, action: ViewTable):
        obs = self.controller.execute_view_table(action.file_path)
        if obs is None or obs == '':
            obs = "Command executed successfully. No output."
        
        return obs

    def execute_read_text_file_action(self, action: ReadTextFile):
        obs = self.controller.execute_read_text_file(action.file_path, action.task_goal)
        if obs is None or obs == '':
            obs = "Command executed successfully. No output."

        return obs

    def execute_code_task_action(self, action: CodeTaskExecutor):
        obs, codes = self.controller.execute_code_task(action.task_goal)
        action.set_code_history(codes)
        if obs is None or obs == '':
            obs = f"Code task executed successfully. No output."
        
        return obs
    
    def execute_sql_task_action(self, action: SQLTaskExecutor):
        obs, sql_task_history = self.controller.execute_sql_task(action.file_path, action.task_goal)
        action.set_code_history(sql_task_history)
        if obs is None or obs == '':
            obs = f"SQL task executed successfully. No output."
        
        return obs

    def execute_extract_archive(self, action: Decompress):
        obs = self.controller.execute_extract_archive(action.file_path)
        if obs is None or obs == '':
            obs = f"Archive extracted successfully. No output."

        return obs
