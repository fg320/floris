"""
Copyright 2017 NREL

Licensed under the Apache License, Version 2.0 (the "License"); you may not use
this file except in compliance with the License. You may obtain a copy of the
License at http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software distributed
under the License is distributed on an "AS IS" BASIS, WITHOUT WARRANTIES OR
CONDITIONS OF ANY KIND, either express or implied. See the License for the
specific language governing permissions and limitations under the License.
"""
from floris import Floris

import OptModules
import numpy as np
from scipy.optimize import minimize
import warnings

warnings.simplefilter('ignore', RuntimeWarning)

# load floris
floris = Floris()

# setup floris and process input file
floris.process_input("floris.json")

# plot initial flow field
floris.farm.flow_field.plot_flow_field_Zplane()

# enter min and max yaw angles for the optimization  
minimum_yaw_angle = 0.0
maximum_yaw_angle = 20.0

opt_yaw_angles = OptModules.wake_steering(floris,minimum_yaw_angle,maximum_yaw_angle)

print('Optimal yaw angles for:')
for i in range(len(opt_yaw_angles)):
	print('Turbine ', i, ' yaw angle = ', np.degrees(resPlant.x[i]))
    
# assign yaw angles to turbines
turbines    = [turbine for _, turbine in floris.farm.flow_field.turbine_map.items()]
for i,turbine in enumerate(turbines):
    turbine.yaw_angle = yawOpt[i]
    
# compute the new wake with yaw angles
floris.farm.flow_field.calculate_wake()

# optimal power 
powerOpt = np.sum([turbine.power for turbine in turbines]) 

# plot results
floris.farm.flow_field.plot_flow_field_Zplane()

print('Power increased by ', 100*(powerOpt-power0)/power0)



