import numpy as np
import logging
from typing import Dict, List, Tuple, Optional, Any
from copy import deepcopy
from dataclasses import dataclass

try:
    import cascade as csc
except ImportError:
    csc = None

try:
    from .nasa_breakup_wrapper import generate_fragments
except ImportError:
    from nasa_breakup_wrapper import generate_fragments

logger = logging.getLogger(__name__)


@dataclass
class ParticleState:
    """
    Represents the state of a particle in the simulation.
    """
    id: int
    position: np.ndarray  # [x, y, z]
    velocity: np.ndarray  # [vx, vy, vz]
    mass: float
    collision_radius: float
    bstar: float = 0.0  # For atmospheric models
    char_length: float = 0.05  # Characteristic length for breakup model (m)
    area_to_mass: float = 0.0  # Area-to-mass ratio
    parent_id: Optional[int] = None  # ID of parent object if this is a fragment
    
    def to_arrays(self) -> Tuple[np.ndarray, np.ndarray]:
        """Return position and velocity as arrays."""
        return self.position.copy(), self.velocity.copy()


class CollisionFragmentHandler:
    """
    Handles collision detection and fragment generation integration.
    """
    
    def __init__(self,
                 min_char_length: float = 0.05,
                 enforce_mass_conservation: bool = True,
                 breakup_model_path: str = "/home/andrea/LSMS_project/NASA-breakup-model-cpp/build_iridium_cosmos/breakupModel"):
        """
        Initialize the collision fragment handler.
        
        Parameters
        ----------
        min_char_length : float
            Minimum characteristic length for fragments in meters
        breakup_model_path : str
            Path to the NASA breakupModel executable
        """
        self.min_char_length = min_char_length
        self.breakup_model_path = breakup_model_path
        self.enforce_mass_conservation = enforce_mass_conservation
        self.next_fragment_id = 50000  # Reserve high IDs for fragments
    
    def set_next_fragment_id(self, next_id: int):
        """Set the starting ID for newly generated fragments."""
        self.next_fragment_id = next_id
    
    def handle_collision(self,
                         sim: Any,
                         pi: int,
                         pj: int,
                         particle_db: Dict[int, ParticleState]) -> Tuple[Dict[int, ParticleState], List[int]]:
        """
        Handle a collision event by generating fragments using NASA Breakup Model.
        
        Parameters
        ----------
        sim : cascade.sim
            The CASCADE simulation object
        pi : int
            Index of first colliding particle
        pj : int
            Index of second colliding particle
        particle_db : Dict[int, ParticleState]
            Database mapping particle indices to their states
            
        Returns
        -------
        Tuple[Dict[int, ParticleState], List[int]]
            Updated particle database and indices of particles to remove (pi and pj)
        """
        
        # Get particle data
        obj1_mass = particle_db[pi].mass
        obj1_id = particle_db[pi].id
        # Extract from CASCADE state matrix
        state = sim.state

        obj1_pos = state[pi, 0:3].copy()
        obj1_vel = state[pi, 3:6].copy()

        obj2_pos = state[pj, 0:3].copy()
        obj2_vel = state[pj, 3:6].copy()
        obj2_mass = particle_db[pj].mass
        obj2_id = particle_db[pj].id
        
        logger.info(f"Collision detected between particles {pi} (id={obj1_id}) and "
                   f"{pj} (id={obj2_id})")
        logger.info(f"  Object 1: mass={obj1_mass:.2e} kg, pos={obj1_pos}, vel={obj1_vel}")
        logger.info(f"  Object 2: mass={obj2_mass:.2e} kg, pos={obj2_pos}, vel={obj2_vel}")
        
        # Generate fragments using NASA Breakup Model
        try:
            fragments, config_file, output_csv = generate_fragments(
                obj1_id, obj1_mass, obj1_pos, obj1_vel,
                obj2_id, obj2_mass, obj2_pos, obj2_vel,
                min_char_length=self.min_char_length,
                breakup_model_path=self.breakup_model_path,
                enforce_mass_conservation=self.enforce_mass_conservation
            )
        except Exception as e:
            logger.error(f"Failed to generate fragments: {str(e)}")
            # Still remove the colliding objects even if breakup fails
            return particle_db, [pi, pj]
        
        # Create particle entries for fragments
        num_fragments = len(fragments['id'])
        logger.info(f"Generated {num_fragments} fragments")
        
        for i in range(num_fragments):
            frag_id = self.next_fragment_id + i
            parent_id = fragments['parent_id'][i]
            frag_pos = fragments['position'][i]
            frag_vel = fragments['velocity'][i]
            frag_mass = fragments['mass'][i]
            frag_char_length = fragments['char_length'][i]
            frag_area_to_mass = fragments['area_to_mass'][i]
            
            # Calculate collision radius from characteristic length
            # Characteristic length is typically related to the sphere radius as: L_c ≈ 2*sqrt(A/pi)
            # where A is the cross-sectional area. For a sphere, r = L_c/2
            frag_collision_radius = 50.0
            
            particle_db[len(particle_db)] = ParticleState(
                id=frag_id,
                parent_id=parent_id,
                position=frag_pos,
                velocity=frag_vel,
                mass=frag_mass,
                collision_radius=frag_collision_radius,
                bstar=0.0,  # Fragments typically have no atmospheric model
                char_length=frag_char_length,
                area_to_mass=frag_area_to_mass
            )
            
            logger.debug(f"  Fragment {i}: id={frag_id}, mass={frag_mass:.2e} kg, "
                        f"char_length={frag_char_length:.4f} m, pos={frag_pos}, vel={frag_vel}")
        
        # Return updated database and particles to remove
        return particle_db, [pi, pj]


def add_fragments_to_simulation(sim, fragments_dict, existing_particles, n_existing):
    """
    Correctly merges survivors and new fragments.
    fragments_dict: dictionary of ParticleState objects
    existing_particles: dictionary of ParticleState objects (survivors only)
    """
    updated_db = deepcopy(existing_particles)
    
    # 1. Get Survivor arrays (from the sim backend)
    # We use n_existing to ensure we don't grab empty slots
    r_ic = np.column_stack([sim.x[:n_existing], sim.y[:n_existing], sim.z[:n_existing]])
    v_ic = np.column_stack([sim.vx[:n_existing], sim.vy[:n_existing], sim.vz[:n_existing]])
    
    # Radii for survivors must come from the dict to stay in sync
    collision_radii = np.array([existing_particles[i].collision_radius for i in range(n_existing)])
    
    # 2. Add Fragments
    # fragments_dict is what comes out of your NASA model parser
    for i, (frag_id, frag) in enumerate(fragments_dict.items()):
        new_idx = n_existing + i
        
        # Append to arrays
        r_ic = np.vstack([r_ic, frag.position.reshape(1,3)])
        v_ic = np.vstack([v_ic, frag.velocity.reshape(1,3)])
        collision_radii = np.append(collision_radii, frag.collision_radius)
        
        # Update database
        updated_db[new_idx] = frag

    return len(r_ic), r_ic, v_ic, collision_radii, updated_db

def handle_collision_and_generate_fragments(sim, pi, pj, particle_db, collision_handler):
    """
    Handle collision detection:
    1. Generate fragments using NASA Breakup Model
    2. Remove collided objects
    3. Add fragments to simulation
    4. Propagate one step to disperse fragments
    """
    
    # Get collision particle data
    obj1_id = particle_db[pi].id
    obj1_mass = particle_db[pi].mass
    obj1_pos = np.array([sim.x[pi], sim.y[pi], sim.z[pi]])
    obj1_vel = np.array([sim.vx[pi], sim.vy[pi], sim.vz[pi]])
    
    obj2_id = particle_db[pj].id
    obj2_mass = particle_db[pj].mass
    obj2_pos = np.array([sim.x[pj], sim.y[pj], sim.z[pj]])
    obj2_vel = np.array([sim.vx[pj], sim.vy[pj], sim.vz[pj]])
    
    logger.info(f"Collision: {obj1_id} (mass={obj1_mass:.0f}kg) + "
               f"{obj2_id} (mass={obj2_mass:.0f}kg)")
    
    # Generate fragments using NASA Breakup Model
    try:
        fragments, config_file, output_csv = generate_fragments(
            obj1_id, obj1_mass, obj1_pos, obj1_vel,
            obj2_id, obj2_mass, obj2_pos, obj2_vel,
            min_char_length=MIN_CHARACTERISTIC_LENGTH,
            breakup_model_path=BREAKUP_MODEL_PATH
        )
    except Exception as e:
        logger.error(f"Fragment generation failed: {e}")
        return None, 0
    
    num_fragments = len(fragments['id'])
    logger.info(f"Generated {num_fragments} fragments")
    
    return fragments, num_fragments

def add_fragments_and_propagate(sim, particle_db, fragments, pi_remove, pj_remove):
    """
    Add generated fragments to CASCADE and propagate for one timestep to disperse them.
    """
    
    # Collect current state (excluding collided objects)
    n_current = sim.x.size
    keep_indices = [i for i in range(n_current) if i not in [pi_remove, pj_remove]]
    
    # Build new state arrays
    r_new = np.column_stack([
        sim.x[keep_indices],
        sim.y[keep_indices],
        sim.z[keep_indices]
    ])
    
    v_new = np.column_stack([
        sim.vx[keep_indices],
        sim.vy[keep_indices],
        sim.vz[keep_indices]
    ])
    
    collision_radii_new = np.array([particle_db[i].collision_radius for i in keep_indices])
    bstars_new = np.array([particle_db[i].bstar for i in keep_indices])
    
    # Add fragments
    for i, frag_id in enumerate(fragments['id']):
        frag_pos = fragments['position'][i]
        frag_parent = fragments['parent_id'][i]
        frag_vel = fragments['velocity'][i]
        frag_mass = fragments['mass'][i]
        frag_char_length = fragments['char_length'][i]
        
        # Calculate collision radius from characteristic length
        frag_collision_radius = 100.0
        
        r_new = np.vstack([r_new, frag_pos])
        v_new = np.vstack([v_new, frag_vel])
        collision_radii_new = np.append(collision_radii_new, frag_collision_radius)
        bstars_new = np.append(bstars_new, 0.0)
        
        # Add to particle database
        new_idx = len(particle_db)
        particle_db[new_idx] = ParticleState(
            id=50000 + i,
            parent_id=frag_parent,
            position=frag_pos,
            velocity=frag_vel,
            mass=frag_mass,
            collision_radius=frag_collision_radius,
            bstar=0.0,
            char_length=frag_char_length
        )
    
    # Update simulation with new state
    if len(r_new) > 0:
        sim.set_new_state(
            r_new[:, 0], r_new[:, 1], r_new[:, 2],
            v_new[:, 0], v_new[:, 1], v_new[:, 2],
            collision_radii_new,
            pars=[bstars_new]
        )
        
        logger.info(f"Updated simulation: {len(r_new)} particles "
                   f"({len(keep_indices)} original + {len(fragments['id'])} fragments)")
        
        # Propagate one step to disperse fragments
        logger.info("Propagating one timestep to disperse fragments...")
        try:
            outcome = sim.step()
            logger.info(f"Dispersal propagation complete (outcome={outcome})")
        except Exception as e:
            logger.warning(f"Dispersal propagation had issue: {e}")
    
    return particle_db


def remove_particles(indices: List[int],
                     r_ic: np.ndarray,
                     v_ic: np.ndarray,
                     collision_radii: np.ndarray,
                     bstars: np.ndarray,
                     particle_db: Dict[int, ParticleState]) -> Tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, Dict[int, ParticleState]]:
    """
    Remove particles from the simulation after collision.
    
    Parameters
    ----------
    indices : List[int]
        Indices of particles to remove
    r_ic : np.ndarray
        Position array
    v_ic : np.ndarray
        Velocity array
    collision_radii : np.ndarray
        Collision radius array
    bstars : np.ndarray
        B* atmospheric parameter array
    particle_db : Dict[int, ParticleState]
        Particle database
        
    Returns
    -------
    Tuple of updated arrays and particle database
    """
    
    # Sort indices in descending order to remove from end first
    indices_to_remove = sorted(set(indices), reverse=True)
    
    r_ic = np.delete(r_ic, indices_to_remove, axis=0)
    v_ic = np.delete(v_ic, indices_to_remove, axis=0)
    collision_radii = np.delete(collision_radii, indices_to_remove, axis=0)
    bstars = np.delete(bstars, indices_to_remove, axis=0)
    
    # Rebuild particle database with updated indices
    new_db = {}
    new_idx = 0
    for old_idx in range(len(indices_to_remove) + len(r_ic)):
        if old_idx not in indices_to_remove and old_idx in particle_db:
            new_db[new_idx] = particle_db[old_idx]
            new_idx += 1
    
    logger.info(f"Removed {len(indices_to_remove)} particles from simulation. "
               f"Remaining: {len(r_ic)}")
    
    return r_ic, v_ic, collision_radii, bstars, new_db


class CollisionAwareSimulation:
    """
    High-level wrapper for CASCADE simulation with collision-based fragment generation.
    
    This class manages the integration of CASCADE's orbital propagation with
    NASA's Breakup Model for realistic debris generation.
    """
    
    def __init__(self,
                 sim: Any,
                 particle_db: Dict[int, ParticleState],
                 min_char_length: float = 0.05,
                 breakup_model_path: str = "/home/andrea/LSMS_project/NASA-breakup-model-cpp/build_iridium_cosmos/breakupModel"):
        """
        Initialize the collision-aware simulation wrapper.
        
        Parameters
        ----------
        sim : cascade.sim
            The CASCADE simulation object
        particle_db : Dict[int, ParticleState]
            Initial particle database
        min_char_length : float
            Minimum characteristic length for fragments
        breakup_model_path : str
            Path to the NASA breakupModel executable
        """
        self.sim = sim
        self.particle_db = deepcopy(particle_db)
        self.collision_handler = CollisionFragmentHandler(min_char_length, breakup_model_path)
        self.collision_handler.set_next_fragment_id(50000)
        self.collision_events = []
        self.n_collisions = 0
        self.n_particles = len(particle_db)
        
    def step_with_collision_handling(self) -> Tuple[bool, Optional[str]]:
        """
        Execute one simulation step with collision detection and handling.
        
        Returns
        -------
        Tuple[bool, Optional[str]]
            (collision_occurred, message)
        """
        
        # Take one simulation step
        outcome = self.sim.step()
        
        if outcome == csc.outcome.collision:
            pi, pj = self.sim.interrupt_info
            
            # Record collision event
            collision_time = self.sim.time
            self.collision_events.append({
                'time': collision_time,
                'object_i': pi,
                'object_j': pj,
                'id_i': self.particle_db[pi].id if pi in self.particle_db else -1,
                'id_j': self.particle_db[pj].id if pj in self.particle_db else -1
            })
            
            logger.info(f"Collision at t={collision_time}: particles {pi} and {pj}")
            
            # Handle the collision
            new_particle_db, particles_to_remove = self.collision_handler.handle_collision(
                self.sim, pi, pj, self.particle_db
            )
            
            # Reconstruct state arrays (excluding colliding objects)
            indices_keep = [i for i in range(self.n_particles) if i not in particles_to_remove]
            
            r_new = np.array([[self.sim.x[i], self.sim.y[i], self.sim.z[i]] for i in indices_keep])
            v_new = np.array([[self.sim.vx[i], self.sim.vy[i], self.sim.vz[i]] for i in indices_keep])
            collision_radii = np.array([self.particle_db[i].collision_radius for i in indices_keep])
            bstars = np.array([self.particle_db[i].bstar for i in indices_keep])
            
            # Add fragments
            fragments_dict = {}
            for new_idx, (_, state) in enumerate(new_particle_db.items()):
                if _ not in self.particle_db:  # New fragment
                    fragments_dict[_] = state
            
            if len(fragments_dict) > 0:
                n_particles, r_ic, v_ic, collision_radii, updated_db = add_fragments_to_simulation(
                    self.sim, fragments_dict, self.particle_db, len(indices_keep)
                )
                
                # Update simulation with new state
                self.sim.set_new_state(
                    r_ic[:, 0], r_ic[:, 1], r_ic[:, 2],
                    v_ic[:, 0], v_ic[:, 1], v_ic[:, 2],
                    collision_radii,
                    pars=[bstars]
                )
                
                self.particle_db = updated_db
                self.n_particles = n_particles
                self.n_collisions += 1
                
                return True, f"Collision handled: {len(fragments_dict)} fragments generated"
            else:
                # No fragments generated, still need to update simulation state
                collision_radii = np.array([self.particle_db[i].collision_radius 
                                          for i in indices_keep if i in self.particle_db])
                bstars = np.array([self.particle_db[i].bstar for i in indices_keep if i in self.particle_db])
                
                self.sim.set_new_state(
                    r_new[:, 0] if len(r_new) > 0 else np.array([]),
                    r_new[:, 1] if len(r_new) > 0 else np.array([]),
                    r_new[:, 2] if len(r_new) > 0 else np.array([]),
                    v_new[:, 0] if len(v_new) > 0 else np.array([]),
                    v_new[:, 1] if len(v_new) > 0 else np.array([]),
                    v_new[:, 2] if len(v_new) > 0 else np.array([]),
                    collision_radii if len(collision_radii) > 0 else np.array([]),
                    pars=[bstars] if len(bstars) > 0 else [[]]
                )
                
                return True, "Collision handled: 0 fragments generated"
        
        return False, None
    
    def get_collision_log(self) -> List[Dict]:
        """Get the log of all collision events."""
        return self.collision_events
    
    def get_statistics(self) -> Dict[str, Any]:
        """Get simulation statistics."""
        return {
            'n_collisions': self.n_collisions,
            'n_particles': self.n_particles,
            'current_time': self.sim.time,
            'collision_events': len(self.collision_events)
        }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    
    print("CASCADE and NASA Breakup Model Integration Module")
    print("=" * 50)
    print("This module provides high-level integration between CASCADE's orbital")
    print("mechanics simulation and the NASA Breakup Model for realistic collision")
    print("debris generation.\n")
    print("Key Classes:")
    print("  - ParticleState: Represents a particle in the simulation")
    print("  - CollisionFragmentHandler: Manages collision-based fragment generation")
    print("  - CollisionAwareSimulation: High-level simulation wrapper")
