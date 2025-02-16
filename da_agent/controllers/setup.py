import logging
import os
import shutil

FILE_PATH = os.path.dirname(os.path.abspath(__file__))
logger = logging.getLogger("da_agent.setup")


class SetupController:
    def __init__(self, container, cache_dir):
        self.cache_dir = cache_dir
        self.container = container
        self.mnt_dir = [mount['Source'] for mount in container.attrs['Mounts']][0]

    def setup_cp_dir(self, dir: str):
        """
        Args:
            dir (str): the directory to copy to the workspace
        """
        mnt_dir = self.mnt_dir

        if os.path.isfile(dir):
            print(f"Warning: {dir} is a file, not a directory. Copying the file to {mnt_dir}.")
            shutil.copy2(dir, mnt_dir)
        elif os.path.isdir(dir):
            print(f"Copying all files in {dir} to {mnt_dir}.")
            shutil.copytree(dir, mnt_dir, dirs_exist_ok=True)
        else:
            print(f"Warning: {dir} is neither a file nor a directory.")
        return

