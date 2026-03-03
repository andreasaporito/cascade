from logging import config
import os
import csv
import yaml
import subprocess
import tempfile
import numpy as np
from pathlib import Path
from typing import Dict, List, Tuple, Optional
import logging

# Set up logging
logger = logging.getLogger(__name__)


class NASABreakupConfig:
    """
    Creates and manages YAML configuration for NASA Breakup Model.
    """
    
    def __init__(self, 
                 breakup_model_path: str = "/home/andrea/LSMS_project/NASA-breakup-model-cpp/build_iridium_cosmos/breakupModel",
                 min_characteristic_length: float = 0.05):
        """
        Initialize the NASA Breakup Model wrapper.
        
        Parameters
        ----------
        breakup_model_path : str
            Path to the NASA breakupModel executable
        min_characteristic_length : float
            Minimum characteristic length for fragments in meters (default 0.05 m)
        """
        self.breakup_model_path = breakup_model_path
        self.min_characteristic_length = min_characteristic_length
        
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
        """
        Create YAML configuration for a collision event.
        
        Parameters
        ----------
        obj1_id : int
            ID of first object
        obj1_mass : float
            Mass of first object in kg
        obj1_pos : np.ndarray
            Position vector of first object [x, y, z] in SI units
        obj1_vel : np.ndarray
            Velocity vector of first object [vx, vy, vz] in SI units
        obj2_id : int
            ID of second object
        obj2_mass : float
            Mass of second object in kg
        obj2_pos : np.ndarray
            Position vector of second object [x, y, z] in SI units
        obj2_vel : np.ndarray
            Velocity vector of second object [vx, vy, vz] in SI units
        temp_dir : str, optional
            Temporary directory for config files
            
        Returns
        -------
        Tuple[str, str]
            Paths to configuration YAML file and output CSV file
        """
        
        if temp_dir is None:
            temp_dir = tempfile.mkdtemp(prefix="cascade_breakup_")
        
        # Create data file content
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
        
        # Create config file content
        output_csv = os.path.join(temp_dir, "fragments.csv")
        output_vtu = os.path.join(temp_dir, "fragments.vtu")
        input_csv = os.path.join(temp_dir, "input.csv")
        input_vtu = os.path.join(temp_dir, "input.vtu")
        config_content = {
            'simulation': {
                'minimalCharacteristicLength': self.min_characteristic_length,
                'simulationType': 'COLLISION',
                'inputSource': [os.path.join(temp_dir, 'collision_data.yaml')]
            },
            'resultOutput': {
                'target': [output_csv, output_vtu]
            },
            'inputOutput': {
                'target': [input_csv, input_vtu]
            }
        }
        
        # Write data file
        data_file = os.path.join(temp_dir, 'collision_data.yaml')
        with open(data_file, 'w') as f:
            yaml.dump(data_content, f, default_flow_style=False)
        
        # Write config file
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
    
    def __init__(self, 
                 breakup_model_path: str = "/home/andrea/LSMS_project/NASA-breakup-model-cpp/build_iridium_cosmos/breakupModel"):
        """
        Initialize the breakup simulator.
        
        Parameters
        ----------
        breakup_model_path : str
            Path to the NASA breakupModel executable
        """
        self.breakup_model_path = breakup_model_path
        
        # Verify the executable exists
        if not os.path.isfile(self.breakup_model_path):
            raise FileNotFoundError(f"NASA breakupModel not found at {self.breakup_model_path}")
        
        if not os.access(self.breakup_model_path, os.X_OK):
            raise PermissionError(f"NASA breakupModel is not executable: {self.breakup_model_path}")
    
    def run_simulation(self, config_file: str) -> str:
        """
        Run the NASA Breakup Model simulation.
        
        Parameters
        ----------
        config_file : str
            Path to configuration YAML file
            
        Returns
        -------
        str
            Path to the output CSV file
        """
        if not os.path.isfile(config_file):
            raise FileNotFoundError(f"Configuration file not found: {config_file}")
        
        try:
            logger.info(f"Running NASA Breakup Model with config: {config_file}")
            result = subprocess.run(
                [self.breakup_model_path, config_file],
                capture_output=True,
                text=True,
                timeout=300  # 5 minute timeout
            )
            
            if result.returncode != 0:
                logger.error(f"Breakup Model failed with return code {result.returncode}")
                logger.error(f"STDOUT: {result.stdout}")
                logger.error(f"STDERR: {result.stderr}")
                raise RuntimeError(f"NASA Breakup Model simulation failed: {result.stderr}")
            
            logger.info("NASA Breakup Model simulation completed successfully")
            logger.info(result.stdout)
            
            # Extract output path from config
            with open(config_file, 'r') as f:
                config = yaml.safe_load(f)
            output_path = config['resultOutput']['target'][0]
            
            return output_path
            
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
        """
        Parse the NASA Breakup Model CSV output.
        
        Parameters
        ----------
        csv_path : str
            Path to the output CSV file
            
        Returns
        -------
        Dict[str, np.ndarray]
            Dictionary containing fragment data with keys:
            - 'id': Fragment IDs
            - 'name': Fragment names
            - 'mass': Fragment masses [kg]
            - 'position': Fragment positions [[x,y,z], ...] in SI units
            - 'velocity': Fragment velocities [[vx,vy,vz], ...] in SI units
            - 'char_length': Characteristic lengths [m]
            - 'area_to_mass': Area-to-mass ratios [m^2/kg]
        """
        
        if not os.path.isfile(csv_path):
            raise FileNotFoundError(f"CSV output file not found: {csv_path}")
        
        fragments = {
            'id': [],
            'name': [],
            'mass': [],
            'position': [],
            'velocity': [],
            'char_length': [],
            'area_to_mass': [],
            'area': []
        }
        
        try:
            with open(csv_path, 'r') as f:
                # Skip header
                reader = csv.reader(f)
                header = next(reader)
                
                for row in reader:
                    if len(row) < 8:  # Minimum expected columns
                        logger.warning(f"Skipping malformed row: {row}")
                        continue
                    
                    try:
                        frag_id = int(row[0])
                        frag_name = row[1]
                        char_length = float(row[3])
                        area_to_mass = float(row[4])
                        area = float(row[5])
                        mass = float(row[6])
                        
                        # Parse velocity [m/s]
                        vel_str = row[8].strip('[]').split()
                        velocity = np.array([float(v) for v in vel_str])
                        
                        # Parse position [m]
                        pos_str = row[9].strip('[]').split()
                        position = np.array([float(p) for p in pos_str])
                        
                        fragments['id'].append(frag_id)
                        fragments['name'].append(frag_name)
                        fragments['mass'].append(mass)
                        fragments['position'].append(position)
                        fragments['velocity'].append(velocity)
                        fragments['char_length'].append(char_length)
                        fragments['area_to_mass'].append(area_to_mass)
                        fragments['area'].append(area)
                        
                    except (ValueError, IndexError) as e:
                        logger.warning(f"Error parsing row {row}: {str(e)}")
                        continue
            
            # Convert lists to numpy arrays
            fragments['id'] = np.array(fragments['id'], dtype=np.int32)
            fragments['mass'] = np.array(fragments['mass'])
            fragments['position'] = np.array(fragments['position'])
            fragments['velocity'] = np.array(fragments['velocity'])
            fragments['char_length'] = np.array(fragments['char_length'])
            fragments['area_to_mass'] = np.array(fragments['area_to_mass'])
            fragments['area'] = np.array(fragments['area'])
            
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
                      breakup_model_path: str = "/home/andrea/LSMS_project/NASA-breakup-model-cpp/build_iridium_cosmos/breakupModel") -> Dict[str, np.ndarray]:
    """
    Generate fragments from a collision using NASA Breakup Model.
    
    This is the main entry point for generating fragments.
    
    Parameters
    ----------
    obj1_id : int
        ID of first colliding object
    obj1_mass : float
        Mass of first object in kg
    obj1_pos : np.ndarray
        Position of first object [x, y, z] in SI units
    obj1_vel : np.ndarray
        Velocity of first object [vx, vy, vz] in SI units
    obj2_id : int
        ID of second colliding object
    obj2_mass : float
        Mass of second object in kg
    obj2_pos : np.ndarray
        Position of second object [x, y, z] in SI units
    obj2_vel : np.ndarray
        Velocity of second object [vx, vy, vz] in SI units
    min_char_length : float
        Minimum characteristic length for fragments in meters (default 0.05 m)
    breakup_model_path : str
        Path to the NASA breakupModel executable
        
    Returns
    -------
    Dict[str, np.ndarray]
        Dictionary containing fragment data
    """
    
    # Use collision location as fragment position
    collision_pos = (np.array(obj1_pos) + np.array(obj2_pos)) / 2.0
    
    # Create configuration
    config_creator = NASABreakupConfig(breakup_model_path, min_char_length)
    config_file, output_csv = config_creator.create_collision_config(
        obj1_id, obj1_mass, obj1_pos, obj1_vel,
        obj2_id, obj2_mass, obj2_pos, obj2_vel, temp_dir="/home/andrea/LSMS_project/NASA-breakup-model-cpp/"
    )
    # Run simulation
    simulator = BreakupSimulator(breakup_model_path)

    print(f"Running NASA Breakup Model simulation with config: {config_file}")

    output_csv = simulator.run_simulation(config_file)

    print(f"Simulation completed. Output CSV: {output_csv}")

    # Parse results and return fragments
    fragments = FragmentParser.parse_csv(output_csv)
    
    # All fragments are initially at the collision location
    # The user requested to displace them in the first timestep
    logger.info(f"Generated {len(fragments['id'])} fragments from collision")
    
    return fragments, config_file, output_csv


if __name__ == "__main__":
    # Example usage - demonstrate the wrapper
    logging.basicConfig(level=logging.INFO)
    
    print("NASA Breakup Model Wrapper Module for CASCADE")
    print("=" * 50)
    print("This module provides functions to integrate the NASA Breakup Model")
    print("into CASCADE simulations for realistic debris generation during collisions.")
    print("\nUsage:")
    print("  from cascade.nasa_breakup_wrapper import generate_fragments")
    print("  fragments = generate_fragments(obj1_id, obj1_mass, obj1_pos, obj1_vel,")
    print("                                  obj2_id, obj2_mass, obj2_pos, obj2_vel)")
