# Copyright 2021 NREL

# Licensed under the Apache License, Version 2.0 (the "License"); you may not
# use this file except in compliance with the License. You may obtain a copy of
# the License at http://www.apache.org/licenses/LICENSE-2.0

# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations under
# the License.

# See https://floris.readthedocs.io for documentation


import numpy as np
import scipy as sp
from scipy.interpolate import griddata

from .utilities import Vec3, cosd, sind, tand


class FlowField:
    """
    FlowField is at the core of the FLORIS software. This class handles
    creating the wind farm domain and initializing and computing the flow field
    based on the chosen wake models and farm model.
    """

    def __init__(self, wind_shear, wind_veer, wake, wind_map, reference_wind_height, reference_turbine_diameter):
        """
        Calls :py:meth:`~.flow_field.FlowField.reinitialize_flow_field`
        to initialize the required data.

        Args:
            wind_shear (float): Wind shear coefficient.
            wind_veer (float): Amount of veer across the rotor.
            wake (:py:class:`~.wake.Wake`): The object containing the model
                definition for the wake calculation.
            turbine_map (:py:obj:`~.turbine_map.TurbineMap`): The object
                describing the farm layout and turbine location.
            wind_map (:py:obj:`~.wind_map.WindMap`): The object describing the
                atmospheric conditions throughout the farm.
            reference_wind_height (float): The focal center of the farm in
                elevation; this value sets where the given wind speed is set
                and about where initial velocity profile is applied.
        """
        self.reinitialize_flow_field(
            wind_shear=wind_shear,
            wind_veer=wind_veer,
            wake=wake,
            wind_map=wind_map,
            with_resolution=wake.velocity_model.model_grid_resolution,
            reference_wind_height=reference_wind_height,
            reference_turbine_diameter=reference_turbine_diameter,
        )
        # TODO consider remapping wake_list with reinitialize flow field
        # self.wake_list = {turbine: None for _, turbine in self.turbine_map.items}

    def reset_uvw(self):
        self.u = self.u_initial.copy()
        self.v = self.v_initial.copy()
        self.w = self.w_initial.copy()

    def _compute_turbine_velocity_deficit(self, x, y, z, turbine, coord, deflection, flow_field):
        """Implement current wake velocity model.

        Args:
            x ([type]): [description]
            y ([type]): [description]
            z ([type]): [description]
            turbine ([type]): [description]
            coord ([type]): [description]
            deflection ([type]): [description]
            flow_field ([type]): [description]
        """
        # velocity deficit calculation
        u_deficit, v_deficit, w_deficit = self.wake.velocity_function(
            x, y, z, turbine, coord, deflection, flow_field
        )

        # calculate spanwise and streamwise velocities if needed
        if hasattr(self.wake.velocity_model, "calculate_VW"):
            v_deficit, w_deficit = self.wake.velocity_model.calculate_VW(
                v_deficit, w_deficit, coord, turbine, flow_field, x, y, z
            )

        return u_deficit, v_deficit, w_deficit

    def _compute_turbine_wake_turbulence(self, ambient_TI, coord_ti, turbine_coord, turbine):
        """Implement current wake turbulence model

        Args:
            x ([type]): [description]
            y ([type]): [description]
            z ([type]): [description]
            turbine ([type]): [description]
            coord ([type]): [description]
            flow_field ([type]): [description]
            turb_u_wake ([type]): [description]
            sorted_map ([type]): [description]

        Returns:
            [type]: [description]
        """

        return self.wake.turbulence_function(
            ambient_TI, coord_ti, turbine_coord, turbine
        )

    def _compute_turbine_wake_deflection(self, x, y, z, turbine, coord, flow_field):
        return self.wake.deflection_function(x, y, z, turbine, coord, flow_field)

    def _calculate_area_overlap(self, wake_velocities, freestream_velocities, turbine):
        """
        compute wake overlap based on the number of points that are not freestream velocity, i.e. affected by the wake
        """
        count = np.sum(freestream_velocities - wake_velocities <= 0.05)
        return (turbine.grid_point_count - count) / turbine.grid_point_count

    # Public methods
    def initialize_velocities(self):
        """
        calculate initial values at these points.

        2) Initializing a gridded curl model (using a call to _discretize_gridded_domain)
        3) Appending points to a non-curl model, this could either be for adding additional points to calculate
            for use in visualization, or else to enable calculation of additional points.  Note this assumes
            the flow has previously been discritized in a prior call to _compute_initialized_domain /
            _discretize_turbine_domain

        Args:
            points: An array that contains the x, y, and z coordinates of
                user-specified points, at which the flow field velocity
                is recorded.
            with_resolution: Vec3
        """
        # set grid point locations in wind_map
        # self.wind_map.grid_layout = (self.x, self.y)

        # interpolate for initial values of flow field grid
        # self.wind_map.calculate_turbulence_intensity(grid=True)
        # self.wind_map.calculate_wind_direction(grid=True)
        # self.wind_map.calculate_wind_speed(grid=True)

        self.u_initial = self.wind_map.grid_wind_speed * (self.z / self.reference_wind_height) ** self.wind_shear
        self.v_initial = np.zeros(np.shape(self.u_initial))
        self.w_initial = np.zeros(np.shape(self.u_initial))

        self.u = self.u_initial.copy()
        self.v = self.v_initial.copy()
        self.w = self.w_initial.copy()

    def reinitialize_flow_field(
        self,
        wind_shear=None,
        wind_veer=None,
        wake=None,
        wind_map=None,
        with_resolution=None,
        bounds_to_set=None,
        reference_wind_height=None,
        reference_turbine_diameter=None
    ):
        """
        Reiniaitilzies the flow field when a parameter needs to be
        updated.

        This method allows for changing/updating a variety of flow
        related parameters. This would typically be used in loops or
        optimizations where the user is calculating AEP over a wind
        rose or investigating wind farm performance at different
        conditions.

        Args:
            wind_shear (float, optional): Wind shear coefficient.
                Defaults to None.
            wind_veer (float, optional): Amount of veer across the rotor.
                Defaults to None.
            wake (:py:class:`~.wake.Wake`, optional): The object containing the
                model definition for the wake calculation. Defaults to None.
            wind_map (:py:obj:`~.wind_map.WindMap`, optional): The object
                describing the atmospheric conditions throughout the farm.
                Defaults to None.
            with_resolution (:py:class:`~.utilities.Vec3`, optional):
                Resolution components to use for the gridded domain in the
                flow field wake calculation. Defaults to None.
            bounds_to_set (list(float), optional): Values representing the
                minimum and maximum values for the domain in each direction:
                [xmin, xmax, ymin, ymax, zmin, zmax]. Defaults to None.
            reference_wind_height (float, optional): The focal center of the
                farm in elevation; this value sets where the given wind speed
                is set and about where initial velocity profile is applied.
                Defaults to None.
        """
        # reset the given parameters
        if wind_map is not None:
            self.wind_map = wind_map
        if wind_shear is not None:
            self.wind_shear = wind_shear
        if wind_veer is not None:
            self.wind_veer = wind_veer
        if reference_wind_height is not None:
            self.reference_wind_height = reference_wind_height
        if reference_turbine_diameter is not None:
            self.reference_turbine_diameter = reference_turbine_diameter
        if wake is not None:
            self.wake = wake
        if with_resolution is None:
            with_resolution = self.wake.velocity_model.model_grid_resolution

        # Set the domain bounds
        self.set_bounds(bounds_to_set=bounds_to_set)

        # reinitialize the flow field
        self._compute_initialized_domain(with_resolution=with_resolution)

        # reinitialize the turbines
        for i, turbine in enumerate(self.turbine_map.turbines):
            turbine.turbulence_intensity = self.wind_map.turbine_turbulence_intensity[
                i
            ]
            turbine.reset_velocities()

    def calculate_wake(self, no_wake=False, points=None, track_n_upstream_wakes=False):
        """
        Updates the flow field based on turbine activity.

        This method rotates the turbine farm such that the wind
        direction is coming from 270 degrees. It then loops over the
        turbines, updating their velocities, calculating the wake
        deflection/deficit, and combines the wake with the flow field.

        Args:
            no_wake (bool, optional): Flag to enable updating the turbine
                properties without adding the wake calculation to the
                freestream flow field. Defaults to *False*.
            points (list(), optional): An array that contains the x-, y-, and
                z-coordinates of user-specified points at which the flow field
                velocity is recorded. Defaults to None.
            track_n_upstream_wakes (bool, optional): When *True*, will keep
                track of the number of upstream wakes a turbine is
                experiencing. Defaults to *False*.
        """
        if self.wake.velocity_model.model_grid_resolution is not None:
            self.reset_uvw()

        if points is not None:
            # add points to flow field grid points
            self._compute_initialized_domain(points=points)

        if track_n_upstream_wakes:
            # keep track of the wakes upstream of each turbine
            self.wake_list = {turbine: 0 for _, turbine in self.turbine_map.items}

        # reinitialize the turbines
        for i, turbine in enumerate(self.turbine_map.turbines):
            turbine.turbulence_intensity = self.wind_map.turbine_turbulence_intensity[
                i
            ]
            turbine.reset_velocities()

        # define the center of rotation with reference to 270 deg as center of
        # flow field
        x0 = np.mean([np.min(self.x), np.max(self.x)])
        y0 = np.mean([np.min(self.y), np.max(self.y)])
        center_of_rotation = Vec3(x0, y0, 0)

        # Rotate the turbines such that they are now in the frame of reference
        # of the wind direction simplifying computing the wakes and wake overlap
        rotated_map = self.turbine_map.rotated(
            self.wind_map.turbine_wind_direction, center_of_rotation
        )

        # rotate the discrete grid and turbine map
        initial_rotated_x, initial_rotated_y, rotated_z = self._rotated_dir(
            self.wind_map.grid_wind_direction, center_of_rotation, rotated_map
        )

        # sort the turbine map
        sorted_map = rotated_map.sorted_in_x_as_list()

        # calculate the velocity deficit and wake deflection on the mesh
        u_wake = np.zeros(np.shape(self.u))

        # Empty the stored variables of v and w at start, these will be updated
        # and stored within the loop
        self.v = np.zeros(np.shape(self.u))
        self.w = np.zeros(np.shape(self.u))

        rx = np.array([coord.x1prime for coord in self.turbine_map.coords])
        ry = np.array([coord.x2prime for coord in self.turbine_map.coords])

        for coord, turbine in sorted_map:
            xloc, yloc = np.array(rx == coord.x1), np.array(ry == coord.x2)
            idx = int(np.where(np.logical_and(yloc, xloc))[0])

            if np.unique(self.wind_map.grid_wind_direction).size == 1:
                # only rotate grid once for homogeneous wind direction
                rotated_x, rotated_y = initial_rotated_x, initial_rotated_y

            else:
                # adjust grid rotation with respect to current turbine for
                # heterogeneous wind direction
                wd = (
                    self.wind_map.turbine_wind_direction[idx]
                    - self.wind_map.grid_wind_direction
                )

                # for straight wakes, change rx[idx] to initial_rotated_x
                xoffset = center_of_rotation.x1 - rx[idx]
                # for straight wakes, change ry[idx] to initial_rotated_y
                yoffset = center_of_rotation.x2 - ry[idx]
                y_grid_offset = xoffset * sind(wd) + yoffset * cosd(wd) - yoffset
                rotated_y = initial_rotated_y - y_grid_offset

                xoffset = center_of_rotation.x1 - initial_rotated_x
                yoffset = center_of_rotation.x2 - initial_rotated_y
                x_grid_offset = xoffset * cosd(wd) - yoffset * sind(wd) - xoffset
                rotated_x = initial_rotated_x - x_grid_offset

            # update the turbine based on the velocity at its hub
            turbine.update_velocities(
                u_wake, coord, self, rotated_x, rotated_y, rotated_z
            )

            # get the wake deflection field
            deflection = self._compute_turbine_wake_deflection(
                rotated_x, rotated_y, rotated_z, turbine, coord, self
            )

            # get the velocity deficit accounting for the deflection
            (
                turb_u_wake,
                turb_v_wake,
                turb_w_wake,
            ) = self._compute_turbine_velocity_deficit(
                rotated_x, rotated_y, rotated_z, turbine, coord, deflection, self
            )

            ###########
            # include turbulence model for the gaussian wake model from
            # Porte-Agel
            if (
                "crespo_hernandez" == self.wake.turbulence_model.model_string
                or self.wake.turbulence_model.model_string == "ishihara_qian"
            ):
                # compute area overlap of wake on other turbines and update
                # downstream turbine turbulence intensities
                for coord_ti, turbine_ti in sorted_map:
                    xloc, yloc = (
                        np.array(rx == coord_ti.x1),
                        np.array(ry == coord_ti.x2),
                    )
                    idx = int(np.where(np.logical_and(yloc, xloc))[0])

                    # placeholder for TI/stability influence on how far
                    # wakes (and wake added TI) propagate downstream
                    downstream_influence_length = 15 * turbine.rotor_diameter

                    if (
                        coord_ti.x1 > coord.x1
                        and np.abs(coord.x2 - coord_ti.x2) < 2 * turbine.rotor_diameter
                        and coord_ti.x1 <= downstream_influence_length + coord.x1
                    ):
                        # only assess the effects of the current wake
                        (
                            freestream_velocities,
                            wake_velocities,
                        ) = turbine_ti.calculate_swept_area_velocities(
                            self.u_initial,
                            coord_ti,
                            rotated_x,
                            rotated_y,
                            rotated_z,
                            additional_wind_speed=self.u_initial - turb_u_wake,
                        )

                        area_overlap = self._calculate_area_overlap(
                            wake_velocities, freestream_velocities, turbine
                        )

                        # placeholder for TI/stability influence on how far
                        # wakes (and wake added TI) propagate downstream
                        downstream_influence_length = 15 * turbine.rotor_diameter

                        if area_overlap > 0.0:
                            # Call wake turbulence model
                            # wake.turbulence_function(inputs)
                            ti_calculation = self._compute_turbine_wake_turbulence(
                                self.wind_map.turbine_turbulence_intensity[idx],
                                coord_ti,
                                coord,
                                turbine,
                            )
                            # multiply by area overlap
                            ti_added = area_overlap * ti_calculation

                            # TODO: need to revisit when we are returning fields of TI
                            turbine_ti.turbulence_intensity = np.max(
                                (
                                    np.sqrt(
                                        ti_added ** 2
                                        + self.wind_map.turbine_turbulence_intensity[
                                            idx
                                        ]
                                        ** 2
                                    ),
                                    turbine_ti.turbulence_intensity,
                                )
                            )

                            if track_n_upstream_wakes:
                                # increment by one for each upstream wake
                                self.wake_list[turbine_ti] += 1

            # combine this turbine's wake into the full wake field
            if not no_wake:
                u_wake = self.wake.combination_function(u_wake, turb_u_wake)

                if self.wake.velocity_model.model_string == "curl":
                    self.v = turb_v_wake
                    self.w = turb_w_wake
                else:
                    self.v = self.v + turb_v_wake
                    self.w = self.w + turb_w_wake

        # apply the velocity deficit field to the freestream
        if not no_wake:
            self.u = self.u_initial - u_wake
            # self.v = self.v_initial + v_wake
            # self.w = self.w_initial + w_wake

        # rotate the grid if it is curl
        if self.wake.velocity_model.model_string == "curl":
            self.x, self.y, self.z = self._rotated_grid(
                -1 * self.wind_map.grid_wind_direction, center_of_rotation
            )
