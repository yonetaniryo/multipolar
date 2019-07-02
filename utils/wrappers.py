""" Wrappers for modifying the dynamics of OpenAI Gym environments.
Author: Mohammadamin Barekatain
Affiliation: TUM & OSX
"""

import importlib
import inspect
import os
import xml.etree.ElementTree as ET
from ast import literal_eval

import gym
import numpy as np
from gym.envs.box2d import LunarLander, BipedalWalker, CarRacing, BipedalWalkerHardcore
from roboschool import RoboschoolHopper


class ModifyBox2DEnvParams(gym.Wrapper):

    def __init__(self, env, verbose, **params):
        """
        Modify the parameters of the given Gym environment with params.

        env: (Gym Environment) the environment to wrap
        params: the parameters to change in env
        """
        gym.Wrapper.__init__(self, env)
        self.params = params

        # find the path to the source code of the environment
        path = inspect.getfile(env.env.__class__)[:-3]
        path = path.split('/')
        idx = path.index('gym')
        path = path[idx:]
        path = ".".join(path)

        # import the environment
        imported_env = importlib.import_module(path)

        # change the parameters of the environment
        for key, val in params.items():
            assert key in vars(imported_env), "{} is not a parameter in the env {}".format(key, imported_env)
            vars(imported_env)[key] = val
            if verbose > 0:
                print("{} changed to {}".format(key, val))


def _get_string_from_tuple(s):
    s = str(s)
    s = s[1:-1]
    return s.replace(',', '')


def _get_end(body):
    s = body.find('geom').attrib['fromto']
    s = s.replace(' ', ',')
    s = literal_eval(s)
    return s[-1]


def _get_length(body):
    s = body.find('geom').attrib['fromto']
    s = s.replace(' ', ',')
    s = np.array(literal_eval(s))
    return np.linalg.norm(s[3:]-s[:3])


def _set_body(body, start, end, pos=True):
    geom = body.find('geom')
    fromto = (0, 0, start, 0, 0, end)
    geom.set('fromto', _get_string_from_tuple(fromto))

    if pos:
        joint = body.find('joint')
        pos = (0, 0, start)
        joint.set('pos', _get_string_from_tuple(pos))


class ModifyHopperEnvParams(gym.Wrapper):

    def __init__(self, env, save_file, verbose, **params):
        """
        Modify the parameters of the given Roboschool Hopper environment with params.

        env: (Gym Environment) the environment to wrap
        params: the parameters to change in env
        """
        gym.Wrapper.__init__(self, env)
        self.params = params

        # find the path to the source code of the environment
        path = inspect.getfile(env.env.__class__)[:-3]
        idx = path.rfind('/')
        path = path[:idx]
        path = os.path.join(path, 'mujoco_assets/hopper.xml')

        # load xml file specifying hopper dynamics and Kinematics
        tree = ET.parse(path)
        root = tree.getroot()
        body_parts = {body.attrib['name']: body for body in root.iter('body')}

        # change the parameters of the environment
        for key, val in params.items():
            val = float(val)
            if 'length' in key:
                key = key.split('_')[0]
                change = False
                for body_name in ['leg', 'thigh', 'torso']:
                    change = change or key == body_name
                    if change:
                        if key == body_name:
                            end = _get_end(body_parts[body_name])
                            start = end + val
                            if verbose > 0:
                                print("length of {} changed to {}".format(body_name, val))
                        else:
                            start = end + _get_length(body_parts[body_name])
                        _set_body(body_parts[body_name], start, end, pos=(body_name != 'torso'))
                        end = start

                if key == 'foot':
                    foot_fromto = (-val/3.0, 0, 0.1, val/3.0*2, 0, 0.1)
                    body_parts[key].find('geom').set('fromto', _get_string_from_tuple(foot_fromto))
                    if verbose > 0:
                        print("length of foot changed to {}".format(val))

                elif not change:
                    raise ValueError('hopper has no body part named {}'.format(key))

            elif key == 'size':
                for name, body in body_parts.items():
                    geom = body.find('geom')
                    size = float(geom.attrib['size'])
                    size = size * val
                    geom.set('size', str(size))
                    if verbose > 0:
                        print("size of {} changed to {}".format(name, size))

            elif key == 'damping' or key == 'armature':
                joint = root.find('default').find('joint')
                joint.set(key, str(val))
                if verbose > 0:
                    print("{} changed to {}".format(key, val))

            elif key == 'friction':
                geom = root.find('default').find('geom')
                val = str(val)
                val = "{} {} {}".format(val, val, val)
                geom.set(key, val)
                if verbose > 0:
                    print("{} changed to {}".format(key, val))

            else:
                raise ValueError('{} is either not a parameter in the env {} or not supported'.format(key, env))

        tree.write(save_file)


def modify_env_params(env, params_path=None, verbose=1, **params):

    if verbose > 0:
        print('changing the environment parameters')

    if isinstance(env.env, LunarLander) or isinstance(env.env, BipedalWalker) \
            or isinstance(env.env, CarRacing) or isinstance(env.env, BipedalWalkerHardcore):
        return ModifyBox2DEnvParams(env=env, verbose=verbose, **params)

    if isinstance(env.env, RoboschoolHopper):
        assert params_path is not None, "params_path must be provided for modifying Hopper"
        save_file = os.path.join(params_path, "Hopper.xml")
        env = ModifyHopperEnvParams(env=env, save_file=save_file, verbose=verbose, **params)
        if hasattr(env.env, 'model_xml'):
            env.env.model_xml = '/' + save_file
        elif hasattr(env.env.env, 'model_xml'):
            env.env.env.model_xml = '/' + save_file
        else:
            raise ValueError("cannot change the env, please check the source code")
        return env

    else:
        raise ValueError("Modifying environment parameters is not supported for {}".format(env.env))


def _get_uniform_sampler(low, high):
    return lambda: np.random.uniform(low, high)


def parse_params_ranges(params_ranges):
    param_sampler = {}
    for config in params_ranges:
        param_config = config.split(',')

        assert len(param_config) == 3, \
            '{} is invalid parameters ranges argument in'.format(config, params_ranges)

        param = param_config[0]
        param_min = literal_eval(param_config[1])
        param_max = literal_eval(param_config[2])

        assert param_min <= param_max, '{} minimum must not be grater than maximum {}'.format(param_min, param_max)

        param_sampler[param] = _get_uniform_sampler(param_min, param_max)

    return param_sampler


class RandomUniformEnvParams(gym.Wrapper):

    def __init__(self, env, save_file, params_ranges, rank=0):

        print(">>> RandomUniformEnvParams <<<")

        gym.Wrapper.__init__(self, env)

        self.param_sampler = parse_params_ranges(params_ranges)
        self.save_file = os.path.join(save_file, "process" + str(rank))
        os.makedirs(self.save_file, exist_ok=True)
        self.env_unwrapped = env

        self.reset()

    def reset(self, **kwargs):
        params = {param: sample_fn() for param, sample_fn in self.param_sampler.items()}

        self.env = modify_env_params(self.env_unwrapped, params_path=self.save_file, verbose=0, **params)

        return super(RandomUniformEnvParams, self).reset(**kwargs)

