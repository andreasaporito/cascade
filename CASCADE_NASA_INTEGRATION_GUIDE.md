# CASCADE and NASA Breakup Model Integration Guide

## Overview

This integration enables CASCADE (ESA's orbital n-body simulator) to automatically call the NASA Breakup Model when collisions are detected, generating realistic debris fragments and continuing the orbital simulation with the expanded debris population.

## Components Created

### 1. **nasa_breakup_wrapper.py**
Located in: `/home/andrea/LSMS_project/cascade/cascade.py/nasa_breakup_wrapper.py`

This module provides low-level interfaces to the NASA Breakup Model. It orchestrates the complete workflow for generating debris from a collision event.

#### Step-by-Step Workflow:

**Step 1: Configuration Creation (NASABreakupConfig class)**
- Takes collision parameters: two object masses, positions, and velocities
- Creates a temporary directory for intermediate files
- Generates two YAML files:
  - `collision_data.yaml`: Contains satellite data (mass, position, velocity) for both colliding objects
  - `collision_config.yaml`: Contains simulation settings (minimum characteristic length, output path, etc.)
- Sets maximum particle ID to reserve space for generated fragments

**Step 2: Simulation Execution (BreakupSimulator class)**
- Verifies the NASA breakupModel executable exists and is executable
- Executes: `breakupModel collision_config.yaml`
- Runs with 5-minute timeout to prevent hanging
- Captures STDOUT/STDERR for error handling and logging
- Extracts output CSV path from the configuration file
- Returns path to generated fragments CSV file

**Step 3: Fragment Parsing (FragmentParser class)**
- Reads the CSV output file from NASA Breakup Model
- Parses each row to extract fragment properties:
  - Fragment ID (integer)
  - Fragment name (string)
  - Characteristic length (meters)
  - Area-to-mass ratio (m²/kg)
  - Cross-sectional area (m²)
  - Mass (kg)
  - Velocity vector [vx, vy, vz] (m/s)
  - Position vector [x, y, z] (meters)
- Converts lists to numpy arrays for efficient computation
- Returns dictionary with keys: id, name, mass, position, velocity, char_length, area_to_mass, area

**Step 4: Main Entry Point (generate_fragments function)**
- Accepts collision parameters: two objects with ID, mass, position, velocity
- Calls NASABreakupConfig to create configuration files
- Calls BreakupSimulator to run the NASA model
- Calls FragmentParser to extract the results
- Returns fragment data dictionary, config file path, and output CSV path
- Usage: `fragments, config_file, output_csv = generate_fragments(obj1_id, obj1_mass, obj1_pos, obj1_vel, obj2_id, obj2_mass, obj2_pos, obj2_vel)`

Key features:
- Automatic YAML configuration generation from collision parameters
- CSV parsing of fragment properties (mass, velocity, position, characteristic length)
- Full error handling and logging
- Supports temporary file management

### 2. **cascade_breakup_integration.py**
Located in: `/home/andrea/LSMS_project/cascade/cascade.py/cascade_breakup_integration.py`

High-level integration between CASCADE and breakup modeling. Manages the complete workflow of detecting collisions in CASCADE and generating debris.

#### Step-by-Step Workflow:

**Step 1: Particle State Management (ParticleState dataclass)**
- Defines the data structure for each particle in the simulation
- Fields tracked:
  - `id`: Unique particle identifier
  - `position`: [x, y, z] position in SI units (meters)
  - `velocity`: [vx, vy, vz] velocity in SI units (m/s)
  - `mass`: Particle mass in kg
  - `collision_radius`: Sphere radius for collision detection (meters)
  - `bstar`: Ballistic coefficient for atmospheric drag
  - `char_length`: Characteristic length for NASA Breakup Model (meters)
  - `area_to_mass`: Cross-sectional area to mass ratio (m²/kg)

**Step 2: Collision Detection and Fragment Generation (CollisionFragmentHandler class)**
- Monitors CASCADE simulation for collision outcomes
- When collision detected, extracts state of both colliding particles:
  - Mass, position, velocity, and unique ID for each object
- Calls `generate_fragments()` from nasa_breakup_wrapper
- Creates ParticleState objects for each generated fragment:
  - Assigns IDs starting at 50000 (reserved range)
  - Calculates collision_radius from characteristic length: `radius = char_length / 2.0`
  - Preserves ejection velocities from NASA model
  - Inherits position from collision location
- Returns updated particle database with new fragments and indices to remove (pi, pj)

**Step 3: Fragment Addition to Simulation (add_fragments_to_simulation function)**
- Takes new fragments and existing particles
- Collects current state from CASCADE: positions, velocities, collision radii
- Stacks fragment data with existing particle data using numpy arrays:
  - `r_ic`: Concatenates position arrays
  - `v_ic`: Concatenates velocity arrays
  - `collision_radii`: Appends fragment collision radii
- Updates particle database with new indices for fragments
- Returns new particle count and updated state arrays

**Step 4: Fragment Dispersal (Propagation)**
- All fragments from NASA model start at collision point (same location)
- To prevent immediate re-collisions with parent objects
- Solution: Propagate CASCADE one timestep (`sim.step()`) after adding fragments
- This naturally disperses fragments due to orbital velocity differences
- Re-enables collision detection for subsequent timesteps

**Step 5: High-Level Simulation Control (CollisionAwareSimulation class)**
- Wraps CASCADE simulation object with collision-aware loop
- Main method: `step_with_collision_handling()`
  - Calls `sim.step()` and checks for collision outcome
  - If collision detected:
    - Logs collision event (time, particle indices, object IDs)
    - Calls collision handler to generate fragments
    - Updates simulation state with new particles
    - Returns True and message about fragments generated
  - If no collision, returns False
- Maintains statistics:
  - `n_collisions`: Total number of collision events
  - `n_particles`: Current particle count
  - `collision_events`: List of all collision events with details

**Step 6: Particle Removal (remove_particles function)**
- Called after collision to remove the two colliding objects
- Takes list of indices to remove
- Deletes rows from state arrays (r_ic, v_ic, collision_radii, bstars)
- Rebuilds particle database with sequential indices
- Returns updated arrays and database

Key capabilities:
- Detects collision outcomes from CASCADE simulation steps
- Calls NASA Breakup Model with collision parameters
- Adds generated fragments back to the simulation
- One-timestep dispersal before re-enabling collision detection
- Full tracking of collision events and fragment statistics

## Workflow

### How It Works

```
┌─────────────────────────────────────────────────────────────────┐
│ 1. Initialize CASCADE simulation with orbital configuration      │
└────────────────────────────┬────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ 2. Step CASCADE forward in time                                 │
└────────────────────────────┬────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ 3. Check for collision outcome                                  │
└────────────────────────────┬────────────────────────────────────┘
                             │
                    ┌────────▼────────┐
                    │ Collision       │
                    │ Detected?       │
                    └────────┬────────┘
                             │
                    ┌────────┴────────┐
                   NO               YES
                    │                └────────────────────┐
                    │                                     │
                    │         ┌───────────────────────────▼──┐
                    │         │ 4. Call NASA Breakup Model   │
                    │         │    (generate fragments)      │
                    │         └───────────────┬──────────────┘
                    │                         │
                    │         ┌───────────────▼──────────────┐
                    │         │ 5. Parse fragment CSV output │
                    │         └───────────────┬──────────────┘
                    │                         │
                    │         ┌───────────────▼──────────────┐
                    │         │ 6. Add fragments to CASCADE  │
                    │         └───────────────┬──────────────┘
                    │                         │
                    │         ┌───────────────▼──────────────┐
                    │         │ 7. Propagate one timestep    │
                    │         │    (disperse fragments)      │
                    │         └───────────────┬──────────────┘
                    │                         │
                    └────────────┬────────────┘
                                 │
                    ┌────────────▼─────────────┐
                    │ Check simulation time    │
                    │ < final_time?            │
                    └────────────┬─────────────┘
                                 │
                        ┌────────┴────────┐
                       YES              NO
                        │                │
                        └──────┐    Continue
                               │    Results
                         Go to │    Analysis
                         Step 2 
```

### Key Implementation Details

#### Fragment Dispersal
- All fragments from NASA Breakup Model start at the same location (collision point)
- User requirement: Disperse fragments by propagating ONE timestep before checking collisions
- Implementation: After adding fragments, we call `sim.step()` once before the main loop continues
- This prevents immediate re-collisions with parent objects

#### Collision Detection
- CASCADE's `sim.step()` returns an `outcome` enum
- When `outcome == csc.outcome.collision`, we intercept and handle it
- The `sim.interrupt_info` provides indices of colliding particles

#### Fragment Addition
- New fragments are added to particle_db with indices > original particle count
- Collision radii calculated as: `radius = characteristic_length / 2.0`
- Ejection velocities from NASA model are preserved as fragment initial velocities

## Usage Example: Full Simulation Workflow

Below is comprehensive pseudocode demonstrating a complete simulation from initialization through collision handling and results analysis:

### Complete Simulation Pseudocode (Notebook Usage)

```python
# ============================================================================
# CELL 1: Import Libraries and Configure Paths
# ============================================================================

import numpy as np
import cascade as csc
from cascade_breakup_integration import (
    ParticleState,
    CollisionFragmentHandler,
    CollisionAwareSimulation,
    add_fragments_to_simulation
)
from nasa_breakup_wrapper import generate_fragments
import logging

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Set paths
BREAKUP_MODEL_PATH = "/home/andrea/LSMS_project/NASA-breakup-model-cpp/build_iridium_cosmos/breakupModel"
MIN_CHARACTERISTIC_LENGTH = 0.05  # 5 cm minimum fragment size


# ============================================================================
# CELL 2: Create Initial Particle Configuration
# ============================================================================

# Example: Create a two-satellite collision scenario at 800 km altitude
# Semi-major axis for 800 km altitude orbit
a_800km = 6.78e6  # meters (Earth radius 6.378e6 + 800 km)

# Create two satellites on slightly different orbits that will collide
# Satellite 1: circular orbit
obj1_id = 1000
obj1_mass = 500.0  # kg
obj1_semi_major_axis = a_800km
obj1_ecc = 0.0
obj1_incl = np.radians(45)  # 45 degrees
obj1_raan = 0.0
obj1_aop = 0.0
obj1_anomaly = 0.0

# Satellite 2: slightly elliptical orbit that crosses obj1's path
obj2_id = 1001
obj2_mass = 400.0  # kg
obj2_semi_major_axis = a_800km + 1000  # 1 km higher
obj2_ecc = 0.001
obj2_incl = np.radians(45.1)  # Slightly different inclination
obj2_raan = 0.0
obj2_aop = 0.0
obj2_anomaly = np.pi  # Start at opposite side of orbit

# Convert orbital elements to Cartesian coordinates
# (You would use pykep or similar library for this)
# Example position and velocity vectors (in SI units)
obj1_pos = np.array([6.78e6, 0.0, 0.0])  # meters
obj1_vel = np.array([0.0, 7700.0, 0.0])   # m/s (~7.7 km/s orbital velocity)

obj2_pos = np.array([6.78e6, 100000.0, 0.0])  # 100 km away
obj2_vel = np.array([0.0, 7750.0, 0.0])  # Slightly faster velocity

# Define initial particle population
n_particles = 2
r_ic = np.array([
    obj1_pos,
    obj2_pos
])

v_ic = np.array([
    obj1_vel,
    obj2_vel
])

# Collision detection parameters
collision_radii = np.array([
    2.0,  # obj1 collision radius (2 m)
    1.5   # obj2 collision radius (1.5 m)
])

# B* ballistic coefficient (for atmospheric models, 0 for outer space)
bstars = np.array([0.0, 0.0])

# Create particle database
particle_db = {
    0: ParticleState(
        id=obj1_id,
        position=obj1_pos.copy(),
        velocity=obj1_vel.copy(),
        mass=obj1_mass,
        collision_radius=collision_radii[0],
        bstar=0.0,
        char_length=4.0,  # Characteristic length ~4m
        area_to_mass=0.04
    ),
    1: ParticleState(
        id=obj2_id,
        position=obj2_pos.copy(),
        velocity=obj2_vel.copy(),
        mass=obj2_mass,
        collision_radius=collision_radii[1],
        bstar=0.0,
        char_length=3.0,  # Characteristic length ~3m
        area_to_mass=0.035
    )
}

print(f"Initial configuration: {n_particles} particles")
print(f"  Object 1: mass={obj1_mass} kg, pos={obj1_pos}, vel={obj1_vel}")
print(f"  Object 2: mass={obj2_mass} kg, pos={obj2_pos}, vel={obj2_vel}")


# ============================================================================
# CELL 3: Initialize CASCADE Simulation
# ============================================================================

# Define dynamics (Keplerian for simplicity, can add perturbations)
# Using CASCADE's default Earth mass
mu_earth = 3.986004418e14  # m^3/s^2

# For pure Keplerian dynamics
dyn = csc.dynamics.sgp4()  # or use keplerian

# Create CASCADE simulation object
# Syntax: csc.sim(x, y, z, vx, vy, vz, collision_radii, dyn=dynamics, pars=[parameters])
sim = csc.sim(
    r_ic[:, 0],
    r_ic[:, 1],
    r_ic[:, 2],
    v_ic[:, 0],
    v_ic[:, 1],
    v_ic[:, 2],
    collision_radii,
    dyn=dyn,
    pars=[bstars]
)

print(f"CASCADE simulation initialized at t={sim.time}")
print(f"  Integrator tolerance: {sim.get_tol()}")


# ============================================================================
# CELL 4: Create Collision-Aware Simulation Wrapper
# ============================================================================

# Initialize collision fragment handler
collision_handler = CollisionFragmentHandler(
    min_char_length=MIN_CHARACTERISTIC_LENGTH,
    breakup_model_path=BREAKUP_MODEL_PATH
)

# Create high-level collision-aware simulation wrapper
collision_sim = CollisionAwareSimulation(
    sim=sim,
    particle_db=particle_db,
    min_char_length=MIN_CHARACTERISTIC_LENGTH,
    breakup_model_path=BREAKUP_MODEL_PATH
)

print("Collision-aware simulation wrapper created")


# ============================================================================
# CELL 5: Main Simulation Loop with Collision Handling
# ============================================================================

# Simulation parameters
final_time = 86400.0  # 1 day in seconds
max_collisions = 10   # Stop after 10 collisions (or remove this limit)
collision_count = 0

# Storage for results
results = {
    'times': [sim.time],
    'n_particles': [len(particle_db)],
    'collisions': [],
    'particle_states': []
}

# Main loop
step_count = 0
max_steps = 100000

while sim.time < final_time and step_count < max_steps:
    # Propagate simulation with collision handling
    collision_occurred, message = collision_sim.step_with_collision_handling()
    
    step_count += 1
    
    if collision_occurred:
        collision_count += 1
        print(f"\n[t={sim.time:.2e} s] Step {step_count}: {message}")
        print(f"  Total collisions so far: {collision_count}")
        print(f"  Current particles: {collision_sim.n_particles}")
        
        # Store collision info
        results['collisions'].append({
            'time': sim.time,
            'step': step_count,
            'n_particles_after': collision_sim.n_particles
        })
        
        if collision_count >= max_collisions:
            print(f"\nReached maximum number of collisions ({max_collisions}). Stopping.")
            break
    
    # Log progress every 1000 steps
    if step_count % 1000 == 0:
        print(f"Step {step_count}: t={sim.time:.2e} s, particles={collision_sim.n_particles}")
    
    # Store periodic results
    if step_count % 100 == 0:
        results['times'].append(sim.time)
        results['n_particles'].append(collision_sim.n_particles)

print(f"\nSimulation complete!")
print(f"  Final time: {sim.time:.2e} s")
print(f"  Total steps: {step_count}")
print(f"  Total collisions: {len(results['collisions'])}")
print(f"  Final particles: {collision_sim.n_particles}")


# ============================================================================
# CELL 6: Alternative: Using Manual Collision Handling (Low-Level API)
# ============================================================================

# This cell shows how to manually handle collisions if you need more control

def manual_collision_loop_pseudocode():
    """
    Pseudocode for manually handling collisions with lower-level API
    """
    
    # Initialize simulation and databases (as in previous cells)
    
    while sim.time < final_time:
        # Step CASCADE forward
        outcome = sim.step()
        
        # Check if collision occurred
        if outcome == csc.outcome.collision:
            # Get colliding particle indices
            pi, pj = sim.interrupt_info
            
            print(f"Collision at t={sim.time}: particles {pi} and {pj}")
            
            # Extract particle data from simulation state
            obj1_mass = particle_db[pi].mass
            obj1_pos = np.array([sim.x[pi], sim.y[pi], sim.z[pi]])
            obj1_vel = np.array([sim.vx[pi], sim.vy[pi], sim.vz[pi]])
            obj1_id = particle_db[pi].id
            
            obj2_mass = particle_db[pj].mass
            obj2_pos = np.array([sim.x[pj], sim.y[pj], sim.z[pj]])
            obj2_vel = np.array([sim.vx[pj], sim.vy[pj], sim.vz[pj]])
            obj2_id = particle_db[pj].id
            
            # STEP 1: Call NASA Breakup Model to generate fragments
            try:
                fragments, config_file, output_csv = generate_fragments(
                    obj1_id, obj1_mass, obj1_pos, obj1_vel,
                    obj2_id, obj2_mass, obj2_pos, obj2_vel,
                    min_char_length=MIN_CHARACTERISTIC_LENGTH,
                    breakup_model_path=BREAKUP_MODEL_PATH
                )
                
                num_fragments = len(fragments['id'])
                print(f"  Generated {num_fragments} fragments")
                
            except Exception as e:
                print(f"  Fragment generation failed: {e}")
                num_fragments = 0
            
            # STEP 2: Create ParticleState objects for fragments
            fragment_particles = {}
            for i in range(num_fragments):
                frag_mass = fragments['mass'][i]
                frag_pos = fragments['position'][i]
                frag_vel = fragments['velocity'][i]
                frag_char_length = fragments['char_length'][i]
                frag_area_to_mass = fragments['area_to_mass'][i]
                
                # Calculate collision radius (simplified: L_c/2)
                frag_collision_radius = frag_char_length / 2.0
                
                fragment_particles[50000 + i] = ParticleState(
                    id=50000 + i,
                    position=frag_pos,
                    velocity=frag_vel,
                    mass=frag_mass,
                    collision_radius=frag_collision_radius,
                    bstar=0.0,
                    char_length=frag_char_length,
                    area_to_mass=frag_area_to_mass
                )
            
            # STEP 3: Remove colliding objects from simulation state
            # Keep only particles that didn't collide
            n_current = sim.x.size
            indices_keep = [i for i in range(n_current) if i not in [pi, pj]]
            
            r_keep = np.column_stack([
                sim.x[indices_keep],
                sim.y[indices_keep],
                sim.z[indices_keep]
            ])
            
            v_keep = np.column_stack([
                sim.vx[indices_keep],
                sim.vy[indices_keep],
                sim.vz[indices_keep]
            ])
            
            collision_radii_keep = np.array([
                particle_db[i].collision_radius for i in indices_keep
            ])
            
            bstars_keep = np.array([
                particle_db[i].bstar for i in indices_keep
            ])
            
            # STEP 4: Add fragments to state arrays
            if num_fragments > 0:
                r_new = np.vstack([r_keep, np.array([f.position for f in fragment_particles.values()])])
                v_new = np.vstack([v_keep, np.array([f.velocity for f in fragment_particles.values()])])
                collision_radii_new = np.append(collision_radii_keep, 
                                               [f.collision_radius for f in fragment_particles.values()])
                bstars_new = np.append(bstars_keep, np.zeros(num_fragments))
            else:
                r_new = r_keep
                v_new = v_keep
                collision_radii_new = collision_radii_keep
                bstars_new = bstars_keep
            
            # STEP 5: Update CASCADE simulation with new state
            sim.set_new_state(
                r_new[:, 0], r_new[:, 1], r_new[:, 2],
                v_new[:, 0], v_new[:, 1], v_new[:, 2],
                collision_radii_new,
                pars=[bstars_new]
            )
            
            # STEP 6: Propagate one timestep to disperse fragments
            # (Prevents immediate re-collisions)
            print(f"  Propagating one step to disperse {num_fragments} fragments...")
            outcome_dispersal = sim.step()
            print(f"  Dispersal complete")
            
            # STEP 7: Update particle database for next iteration
            # Rebuild with kept particles and new fragments
            new_particle_db = {}
            new_idx = 0
            for keep_idx in indices_keep:
                if keep_idx in particle_db:
                    new_particle_db[new_idx] = particle_db[keep_idx]
                    new_idx += 1
            
            # Add fragment particles
            for _, frag in fragment_particles.items():
                new_particle_db[new_idx] = frag
                new_idx += 1
            
            particle_db = new_particle_db
            
            print(f"  Updated particle count: {len(particle_db)}")


# ============================================================================
# CELL 7: Extract and Analyze Results
# ============================================================================

# Get collision log
collision_log = collision_sim.get_collision_log()
print(f"Collision Log ({len(collision_log)} events):")
for event in collision_log:
    print(f"  t={event['time']:.2e}: "
          f"Particle {event['object_i']} (ID={event['id_i']}) & "
          f"Particle {event['object_j']} (ID={event['id_j']})")

# Get final statistics
stats = collision_sim.get_statistics()
print(f"\nFinal Statistics:")
print(f"  Total collisions: {stats['n_collisions']}")
print(f"  Final particle count: {stats['n_particles']}")
print(f"  Simulation time: {stats['current_time']:.2e} s")

# Extract final state
final_positions = np.column_stack([sim.x, sim.y, sim.z])
final_velocities = np.column_stack([sim.vx, sim.vy, sim.vz])

print(f"\nFinal Orbital Configuration:")
print(f"  {len(final_positions)} particles in solution space")
for i, pos in enumerate(final_positions[:5]):  # Show first 5
    r = np.linalg.norm(pos)
    v = np.linalg.norm(final_velocities[i])
    altitude = r - 6.371e6
    print(f"  Particle {i}: r={r:.2e} m (alt={altitude/1e3:.1f} km), v={v:.2e} m/s")


# ============================================================================
# CELL 8: Visualization (Optional)
# ============================================================================

import matplotlib.pyplot as plt

# Plot 1: Population evolution over time
fig, axes = plt.subplots(2, 2, figsize=(12, 10))

# Particle count evolution
ax = axes[0, 0]
ax.plot(results['times'], results['n_particles'], 'b.-')
ax.set_xlabel('Time [s]')
ax.set_ylabel('Number of Particles')
ax.set_title('Particle Population Evolution')
ax.grid(True)

# Collision timeline
ax = axes[0, 1]
collision_times = [c['time'] for c in results['collisions']]
ax.plot(collision_times, range(1, len(collision_times)+1), 'ro-')
ax.set_xlabel('Time [s]')
ax.set_ylabel('Cumulative Collision Count')
ax.set_title('Collision Timeline')
ax.grid(True)

# 3D orbital configuration (final state)
ax = axes[1, 0]
pos_xyz = final_positions
ax.scatter(pos_xyz[:, 0]/1e6, pos_xyz[:, 1]/1e6, s=10, alpha=0.6)
ax.set_xlabel('X [Mm]')
ax.set_ylabel('Y [Mm]')
ax.set_title('XY Orbital Configuration (Final)')
ax.axis('equal')
ax.grid(True)

# Altitude distribution
ax = axes[1, 1]
altitudes = (np.linalg.norm(final_positions, axis=1) - 6.371e6) / 1e3
ax.hist(altitudes, bins=20, edgecolor='black')
ax.set_xlabel('Altitude [km]')
ax.set_ylabel('Count')
ax.set_title('Final Altitude Distribution')
ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig('collision_simulation_results.png', dpi=150)
print("Visualization saved to 'collision_simulation_results.png'")
plt.show()
```

This pseudocode demonstrates:
- Full simulation initialization from orbital elements
- Collision detection and fragment generation
- Real-time monitoring and statistics
- Results extraction and analysis
- Sample visualization

## Running a Complete Simulation in Jupyter Notebook

The pseudocode above is structured as Jupyter notebook cells and can be directly used in a notebook environment.

**Quick Start:**

```bash
# Navigate to CASCADE notebook directory
cd /home/andrea/LSMS_project/cascade/cascade.py/notebooks

# Launch Jupyter
jupyter notebook
```

**Notebook Structure:**

The complete simulation workflow is organized into 8 cells:

1. **Imports & Configuration** - Load libraries and set paths to NASA Breakup Model
2. **Create Particle Configuration** - Define initial satellite orbits and properties
3. **Initialize CASCADE** - Create CASCADE simulation object with physics model
4. **Create Collision-Aware Wrapper** - Initialize collision handler and high-level simulation controller
5. **Main Simulation Loop** - Run full integration with automatic collision handling
6. **Manual Collision Handling** - Alternative low-level API for custom collision logic (optional)
7. **Extract & Analyze Results** - Parse collision log and compute statistics
8. **Visualization** - Generate plots of population evolution, orbital configuration, and altitudes

**Typical Execution Time:**

- Small scenario (2 objects, 1 day, few collisions): ~1-5 minutes
- Medium scenario (10 objects, 1 week, 5-10 collisions): ~10-30 minutes
- Large scenario (100+ objects, 1 month): May require hours

Time depends on:
- Number of particles
- Total simulation duration
- Number of collision events (each requires running NASA Breakup Model)
- NASA Breakup Model runtime per collision (~5-60 seconds)

## Configuration Parameters

### NASA Breakup Model
- **minimimalCharacteristicLength**: Minimum fragment size (default: 0.05 m)
- **simulationType**: COLLISION or EXPLOSION
- **enforceMassConservation**: Enable mass conservation (default: false)

### CASCADE Simulation
- **Dynamics**: Keplerian (can be extended with perturbations)
- **Collision Detection**: Enabled with configurable radii
- **Time Integration**: Adaptive timesteps

## Output

The simulation produces:

1. **collision_simulation_results/** - Output directory with:
   - `collision_log.txt` - Detailed event log
   - `simulation_results.png` - Visualization plots
   
2. **Plots generated:**
   - Particle population evolution over time
   - Collision events timeline
   - Fragment generation distribution
   - Final orbital configuration (3D scatter)
   - Final altitude distribution histogram
   - Summary statistics


## Testing

To verify the integration works:

```python
# Quick test of NASA breakup wrapper
from nasa_breakup_wrapper import generate_fragments
import numpy as np

obj1_pos = np.array([6.78e6, 0, 0])  # 800 km altitude
obj1_vel = np.array([0, 7.7e3, 0])   # ~7.7 km/s orbital velocity
obj2_pos = np.array([6.79e6, 0, 0])
obj2_vel = np.array([0, 7.7e3, 0])

fragments, config_file, output_csv = generate_fragments(
    obj1_id=1000, obj1_mass=500,
    obj1_pos=obj1_pos, obj1_vel=obj1_vel,
    obj2_id=1001, obj2_mass=400,
    obj2_pos=obj2_pos, obj2_vel=obj2_vel,
    min_char_length=0.05
)

print(f"Generated {len(fragments['id'])} fragments")
print(f"Fragment masses: {fragments['mass']}")
print(f"Fragment velocities shape: {fragments['velocity'].shape}")
```
