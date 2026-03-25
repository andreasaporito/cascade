from logging import config
import os
import csv
import yaml
import subprocess
import tempfile
import shutil
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import logging

logger = logging.getLogger(__name__)


# ── Auto-build configuration ───────────────────────────────────────────────
# The repo will be cloned and built here, next to this file.
# This means the binary lives inside the project, not on a specific user's machine.
_THIS_DIR = Path(__file__).parent.resolve()
_DEFAULT_REPO_URL = "https://github.com/andreasaporito/NASA-breakup-model-cpp.git"
_DEFAULT_BUILD_DIR = _THIS_DIR / "_nasa_breakup_build"
_DEFAULT_EXECUTABLE = _DEFAULT_BUILD_DIR / "build" / "breakupModel"


def _ensure_executable(breakup_model_path: Optional[str] = None) -> str:
    """
    Return a valid path to the breakupModel executable.

    Resolution order
    ----------------
    1. Explicit path passed by the caller  (backward-compatible with old code)
    2. BREAKUP_MODEL_PATH environment variable
    3. Previously auto-built binary next to this file  (avoids rebuilding every run)
    4. Auto-clone + cmake build from GitHub  (first-time setup on any machine)

    Parameters
    ----------
    breakup_model_path : str, optional
        Explicit path to an existing binary. If given and valid, used as-is.

    Returns
    -------
    str
        Absolute path to a working breakupModel executable.
    """

    # 1. Explicit path
    if breakup_model_path is not None:
        if os.path.isfile(breakup_model_path) and os.access(breakup_model_path, os.X_OK):
            logger.debug(f"Using provided executable: {breakup_model_path}")
            return breakup_model_path
        logger.warning(
            f"Provided breakup_model_path '{breakup_model_path}' not found or not executable. "
            "Falling back to auto-build."
        )

    # 2. Environment variable
    env_path = os.environ.get("BREAKUP_MODEL_PATH")
    if env_path:
        if os.path.isfile(env_path) and os.access(env_path, os.X_OK):
            logger.debug(f"Using BREAKUP_MODEL_PATH env: {env_path}")
            return env_path
        logger.warning(f"BREAKUP_MODEL_PATH='{env_path}' not found. Falling back to auto-build.")

    # 3. Cached auto-built binary (already compiled on this machine before)
    if _DEFAULT_EXECUTABLE.is_file() and os.access(str(_DEFAULT_EXECUTABLE), os.X_OK):
        logger.debug(f"Using cached auto-build at {_DEFAULT_EXECUTABLE}")
        return str(_DEFAULT_EXECUTABLE)

    # 4. First-time auto-build
    logger.info("breakupModel executable not found. Cloning and building from GitHub...")
    _clone_and_build(_DEFAULT_REPO_URL, _DEFAULT_BUILD_DIR)

    if not (_DEFAULT_EXECUTABLE.is_file() and os.access(str(_DEFAULT_EXECUTABLE), os.X_OK)):
        raise RuntimeError(
            f"Auto-build finished but executable not found at {_DEFAULT_EXECUTABLE}.\n"
            "Check the cmake output above for errors.\n"
            "Alternatively, set BREAKUP_MODEL_PATH=/path/to/breakupModel in your environment."
        )

    logger.info(f"Auto-build successful: {_DEFAULT_EXECUTABLE}")
    return str(_DEFAULT_EXECUTABLE)


def _clone_and_build(repo_url: str, build_dir: Path) -> None:
    """
    Clone the breakup model repo from GitHub and build it with CMake.

    This is called only once per machine. The result is cached in
    _nasa_breakup_build/ next to this file.

    Parameters
    ----------
    repo_url : str
        GitHub URL to clone.
    build_dir : Path
        Root directory for the clone + build (created if needed).
    """

    # Verify required tools are available
    for tool in ("git", "cmake", "make"):
        if shutil.which(tool) is None:
            raise EnvironmentError(
                f"'{tool}' is required but was not found on PATH.\n"
                "  Linux:  sudo apt install git cmake build-essential libtbb-dev\n"
                "  macOS:  brew install cmake git"
            )

    repo_dir      = build_dir / "repo"
    cmake_out_dir = build_dir / "build"

    # --- Clone (skip if already done) ---
    if not (repo_dir / "CMakeLists.txt").exists():
        logger.info(f"Cloning {repo_url} ...")
        build_dir.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            ["git", "clone", "--depth", "1", repo_url, str(repo_dir)],
            capture_output=True, text=True
        )
        if result.returncode != 0:
            raise RuntimeError(f"git clone failed:\n{result.stderr}")
        logger.info("Clone complete.")
    else:
        logger.info(f"Repo already present at {repo_dir}, skipping clone.")

    # --- CMake configure ---
    cmake_out_dir.mkdir(parents=True, exist_ok=True)
    logger.info("Configuring with CMake ...")
    result = subprocess.run(
        ["cmake", "-S", str(repo_dir), "-B", str(cmake_out_dir),
         "-DCMAKE_BUILD_TYPE=Release"],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"cmake configure failed:\n{result.stderr}")

    # --- Build ---
    n_cores = str(os.cpu_count() or 2)
    logger.info(f"Building with {n_cores} cores ...")
    result = subprocess.run(
        ["cmake", "--build", str(cmake_out_dir), "--parallel", n_cores],
        capture_output=True, text=True
    )
    if result.returncode != 0:
        raise RuntimeError(f"cmake build failed:\n{result.stderr}")

    # The upstream CMakeLists.txt places the binary at <cmake_out_dir>/breakupModel
    built_binary = cmake_out_dir / "breakupModel"
    if not built_binary.exists():
        raise RuntimeError(
            f"Build reported success but binary not found at {built_binary}.\n"
            f"cmake stdout:\n{result.stdout}"
        )

    # Copy to the stable location that _ensure_executable checks.
    # If cmake already put the binary there (same path), skip the copy.
    target = _DEFAULT_BUILD_DIR / "build" / "breakupModel"
    target.parent.mkdir(parents=True, exist_ok=True)
    if built_binary.resolve() != target.resolve():
        shutil.copy2(str(built_binary), str(target))
    os.chmod(str(target), 0o755)
    logger.info(f"Binary installed at {target}")


# ── Everything below is IDENTICAL to your original file ───────────────────
# The only change is that breakup_model_path defaults to None everywhere,
# so _ensure_executable() handles the path resolution transparently.

class NASABreakupConfig:
    """
    Creates and manages YAML configuration for NASA Breakup Model.
    """
    
    def __init__(self, 
                 breakup_model_path: str = None,
                 min_characteristic_length: float = 0.05,
                 enforce_mass_conservation: bool = True):
        self.breakup_model_path = _ensure_executable(breakup_model_path)
        self.min_characteristic_length = min_characteristic_length
        self.enforce_mass_conservation = enforce_mass_conservation
        
    def create_collision_config(self,
                               obj1_id: int,
                               obj1_mass: float,
                               obj1_pos: np.ndarray,
                               obj1_vel: np.ndarray,
                               obj2_id: int,
                               obj2_mass: float,
                               obj2_pos: np.ndarray,
                               obj2_vel: np.ndarray,
                               temp_dir: Optional[str] = None) -> Tuple[str, str]:
        
        if temp_dir is None:
            temp_dir = tempfile.mkdtemp(prefix="cascade_breakup_")
        
        data_content = {
            'satellites': [
                {
                    'name': f'Object_{obj1_id}',
                    'id': obj1_id,
                    'satType': 'SPACECRAFT',
                    'mass': float(obj1_mass),
                    'position': [float(obj1_pos[0]), float(obj1_pos[1]), float(obj1_pos[2])],
                    'velocity': [float(obj1_vel[0]), float(obj1_vel[1]), float(obj1_vel[2])]
                },
                {
                    'name': f'Object_{obj2_id}',
                    'id': obj2_id,
                    'satType': 'SPACECRAFT',
                    'mass': float(obj2_mass),
                    'position': [float(obj2_pos[0]), float(obj2_pos[1]), float(obj2_pos[2])],
                    'velocity': [float(obj2_vel[0]), float(obj2_vel[1]), float(obj2_vel[2])]
                }
            ]
        }
        
        output_csv = os.path.join(temp_dir, "fragments.csv")
        output_vtu = os.path.join(temp_dir, "fragments.vtu")
        input_csv  = os.path.join(temp_dir, "input.csv")
        input_vtu  = os.path.join(temp_dir, "input.vtu")

        config_content = {
            'simulation': {
                'minimalCharacteristicLength': self.min_characteristic_length,
                'enforceMassConservation': self.enforce_mass_conservation,
                'simulationType': 'COLLISION',
                'inputSource': [os.path.join(temp_dir, 'collision_data.yaml')]
            },
            'resultOutput': {'target': [output_csv, output_vtu]},
            'inputOutput':  {'target': [input_csv,  input_vtu]}
        }
        
        data_file = os.path.join(temp_dir, 'collision_data.yaml')
        with open(data_file, 'w') as f:
            yaml.dump(data_content, f, default_flow_style=False)
        
        config_file = os.path.join(temp_dir, 'collision_config.yaml')
        with open(config_file, 'w') as f:
            yaml.dump(config_content, f, default_flow_style=False)
        
        logger.info(f"Created collision config at {config_file}")
        logger.info(f"Output will be written to {output_csv}")
        
        return config_file, output_csv


class BreakupSimulator:
    """
    Manages execution of NASA Breakup Model simulations.
    """
    
    def __init__(self, breakup_model_path: str = None):
        self.breakup_model_path = _ensure_executable(breakup_model_path)
        
        if not os.path.isfile(self.breakup_model_path):
            raise FileNotFoundError(f"NASA breakupModel not found at {self.breakup_model_path}")
        if not os.access(self.breakup_model_path, os.X_OK):
            raise PermissionError(f"NASA breakupModel is not executable: {self.breakup_model_path}")
    
    def run_simulation(self, config_file: str) -> str:
        if not os.path.isfile(config_file):
            raise FileNotFoundError(f"Configuration file not found: {config_file}")
        
        try:
            logger.info(f"Running NASA Breakup Model with config: {config_file}")
            result = subprocess.run(
                [self.breakup_model_path, config_file],
                capture_output=True,
                text=True,
                timeout=300
            )
            
            if result.returncode != 0:
                logger.error(f"Breakup Model failed with return code {result.returncode}")
                logger.error(f"STDOUT: {result.stdout}")
                logger.error(f"STDERR: {result.stderr}")
                raise RuntimeError(f"NASA Breakup Model simulation failed: {result.stderr}")
            
            logger.info("NASA Breakup Model simulation completed successfully")
            logger.info(result.stdout)
            
            with open(config_file, 'r') as f:
                config = yaml.safe_load(f)
            return config['resultOutput']['target'][0]
            
        except subprocess.TimeoutExpired:
            raise RuntimeError("NASA Breakup Model simulation timed out")
        except Exception as e:
            logger.error(f"Error running breakup simulation: {str(e)}")
            raise


class FragmentParser:
    """
    Parses NASA Breakup Model CSV output.
    """
    
    @staticmethod
    def parse_csv(csv_path: str) -> Dict[str, np.ndarray]:
        if not os.path.isfile(csv_path):
            raise FileNotFoundError(f"CSV output file not found: {csv_path}")
        
        fragments = {
            'id': [], 'name': [], 'parent_id': [],
            'mass': [], 'position': [], 'velocity': [],
            'char_length': [], 'area_to_mass': [], 'area': []
        }
        
        try:
            with open(csv_path, 'r') as f:
                reader = csv.reader(f)
                next(reader)  # skip header
                
                for row in reader:
                    if len(row) < 8:
                        logger.warning(f"Skipping malformed row: {row}")
                        continue
                    
                    try:
                        frag_id       = int(row[0])
                        frag_name     = row[1]
                        parent_id_str = frag_name.split('_')[1].split('-')[0]
                        parent_id     = int(parent_id_str)
                        char_length   = float(row[3])
                        area_to_mass  = float(row[4])
                        area          = float(row[5])
                        mass          = float(row[6])
                        
                        vel_str  = row[8].strip('[]').split()
                        velocity = np.array([float(v) for v in vel_str])
                        
                        pos_str  = row[9].strip('[]').split()
                        position = np.array([float(p) for p in pos_str])
                        
                        fragments['id'].append(frag_id)
                        fragments['name'].append(frag_name)
                        fragments['parent_id'].append(parent_id)
                        fragments['mass'].append(mass)
                        fragments['position'].append(position)
                        fragments['velocity'].append(velocity)
                        fragments['char_length'].append(char_length)
                        fragments['area_to_mass'].append(area_to_mass)
                        fragments['area'].append(area)
                        
                    except (ValueError, IndexError) as e:
                        logger.warning(f"Error parsing row {row}: {str(e)}")
                        continue
            
            fragments['id']           = np.array(fragments['id'],        dtype=np.int32)
            fragments['parent_id']    = np.array(fragments['parent_id'], dtype=np.int32)
            fragments['mass']         = np.array(fragments['mass'])
            fragments['position']     = np.array(fragments['position'])
            fragments['velocity']     = np.array(fragments['velocity'])
            fragments['char_length']  = np.array(fragments['char_length'])
            fragments['area_to_mass'] = np.array(fragments['area_to_mass'])
            fragments['area']         = np.array(fragments['area'])
            
            logger.info(f"Parsed {len(fragments['id'])} fragments from {csv_path}")
            return fragments
            
        except Exception as e:
            logger.error(f"Error parsing CSV file: {str(e)}")
            raise


def generate_fragments(obj1_id: int,
                       obj1_mass: float,
                       obj1_pos: np.ndarray,
                       obj1_vel: np.ndarray,
                       obj2_id: int,
                       obj2_mass: float,
                       obj2_pos: np.ndarray,
                       obj2_vel: np.ndarray,
                       min_char_length: float = 0.05,
                       enforce_mass_conservation: bool = True,
                       breakup_model_path: str = None) -> Dict[str, np.ndarray]:
    """
    Generate fragments from a collision using the NASA Breakup Model.

    Parameters
    ----------
    breakup_model_path : str, optional
        Path to the NASA breakupModel executable.
        Defaults to None, which triggers automatic path resolution:
          1. BREAKUP_MODEL_PATH environment variable
          2. Auto-clone + build from GitHub (result cached locally)
        Pass an explicit path only if you have a custom build somewhere.
    """

    config_creator = NASABreakupConfig(
        breakup_model_path, min_char_length, enforce_mass_conservation
    )

    # Use a project-local temp dir so paths never contain a username
    temp_dir = str(_THIS_DIR / "_cascade_breakup_tmp")
    os.makedirs(temp_dir, exist_ok=True)

    config_file, output_csv = config_creator.create_collision_config(
        obj1_id, obj1_mass, obj1_pos, obj1_vel,
        obj2_id, obj2_mass, obj2_pos, obj2_vel,
        temp_dir=temp_dir
    )

    simulator = BreakupSimulator(config_creator.breakup_model_path)
    print(f"Running NASA Breakup Model simulation with config: {config_file}")

    output_csv = simulator.run_simulation(config_file)
    print(f"Simulation completed. Output CSV: {output_csv}")

    fragments = FragmentParser.parse_csv(output_csv)
    logger.info(f"Generated {len(fragments['id'])} fragments from collision")

    return fragments, config_file, output_csv


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("NASA Breakup Model Wrapper Module for CASCADE")
    print("=" * 50)
    print("This module provides functions to integrate the NASA Breakup Model")
    print("into CASCADE simulations for realistic debris generation during collisions.")
    print("\nUsage:")
    print("  from nasa_breakup_wrapper import generate_fragments")
    print("  fragments, cfg, csv = generate_fragments(")
    print("      obj1_id, obj1_mass, obj1_pos, obj1_vel,")
    print("      obj2_id, obj2_mass, obj2_pos, obj2_vel)")