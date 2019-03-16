import numpy as np


def hyperparam_optimization(algo, model_fn, env_fn, n_trials=10, n_timesteps=5000, hyperparams=None,
                            n_jobs=1):
    """
    :param algo: (str)
    :param model_fn: (func)
    :param env_fn: (func)
    :param n_trials: (int)
    :param n_timesteps: (int)
    :param hyperparams: (dict)
    :param n_jobs: (int)
    :return: (pd.Dataframe)
    """
    # Avoid showing tf logging
    import optuna
    from optuna.pruners import SuccessiveHalvingPruner, MedianPruner
    from optuna.samplers import RandomSampler, TPESampler
    # TODO: eval each hyperparams several times to account for noisy evaluation

    if hyperparams is None:
        hyperparams = {}

    # test during 5 episodes
    n_test_episodes = 5
    # evaluate every 20th of the maximum budget per iteration
    n_evaluations = 20
    evaluate_interval = int(n_timesteps / n_evaluations)
    deterministic_eval = False
    # n_warmup_steps: Disable pruner until the trial reaches the given number of step.
    median_pruner = MedianPruner(n_startup_trials=5, n_warmup_steps=2)
    # pruner = SuccessiveHalvingPruner(min_resource=1, reduction_factor=4, min_early_stopping_rate=0)
    sampler = RandomSampler()
    # sampler = TPESampler()
    study = optuna.create_study(sampler=sampler, pruner=median_pruner)
    sampler = HYPERPARAMS_SAMPLER[algo]

    def objective(trial):

        kwargs = hyperparams.copy()
        kwargs.update(sampler(trial))

        def callback(_locals, _globals):
            """
            Callback for monitoring learning progress.

            :param _locals: (dict)
            :param _globals: (dict)
            :return: (bool) If False: stop training
            """
            self_ = _locals['self']
            trial = self_.trial

            # Initialize variables
            if not hasattr(self_, 'is_pruned'):
                self_.is_pruned = False
                self_.last_mean_test_reward = -np.inf
                self_.last_time_evaluated = 0
                self_.eval_idx = 0

            if (self_.num_timesteps - self_.last_time_evaluated) < evaluate_interval:
                return True

            self_.last_time_evaluated = self_.num_timesteps

            # Evaluate the trained agent on the test env
            rewards = []
            n_episodes, reward_sum = 0, 0.0
            obs = self_.test_env.reset()
            while n_episodes < n_test_episodes:
                action, _ = self_.predict(obs, deterministic=deterministic_eval)
                obs, reward, done, _ = self_.test_env.step(action)
                reward_sum += reward

                if done:
                    rewards.append(reward_sum)
                    reward_sum = 0.0
                    n_episodes += 1
                    obs = self_.test_env.reset()

            mean_reward = np.mean(rewards)
            self_.last_mean_test_reward = mean_reward
            self_.eval_idx += 1

            # report best or report current ?
            # report num_timesteps or elasped time ?
            trial.report(-1 * mean_reward, self_.eval_idx)
            # Prune trial if need
            if trial.should_prune(self_.eval_idx):
                self_.is_pruned = True
                return False

            return True

        model = model_fn(**kwargs)
        model.test_env = env_fn(n_envs=1)
        model.trial = trial
        try:
            model.learn(n_timesteps, callback=callback)
        except Exception:
            # Free memory
            model.env.close()
            model.test_env.close()
            raise
        is_pruned = False
        cost = np.inf
        if hasattr(model, 'is_pruned'):
            is_pruned = model.is_pruned
            cost = -1 * model.last_mean_test_reward
        del model.env, model.test_env
        del model

        if is_pruned:
            raise optuna.structs.TrialPruned()

        return cost

    try:
        study.optimize(objective, n_trials=n_trials, n_jobs=n_jobs)
    except KeyboardInterrupt:
        pass

    print('Number of finished trials: ', len(study.trials))

    print('Best trial:')
    trial = study.best_trial

    print('  Value: ', trial.value)

    print('  Params: ')
    for key, value in trial.params.items():
        print('    {}: {}'.format(key, value))

    return study.trials_dataframe()


def sample_ppo2_params(trial):
    """
    Sampler for PPO2 hyperparams.

    :param trial: (optuna.trial)
    :return: (dict)
    """
    batch_size = trial.suggest_categorical('batch_size', [32, 64, 128, 256])
    n_steps = trial.suggest_categorical('n_steps', [16, 32, 64, 128, 256, 512, 1024, 2048])
    gamma = trial.suggest_categorical('gamma', [0.9, 0.95, 0.98, 0.99, 0.995, 0.999, 0.9999])
    learning_rate = trial.suggest_loguniform('lr', 1e-5, 1)
    ent_coef = trial.suggest_loguniform('ent_coef', 0.00000001, 0.1)
    cliprange = trial.suggest_categorical('cliprange', [0.1, 0.2, 0.3, 0.4])
    noptepochs = trial.suggest_categorical('noptepochs', [1, 5, 10, 20, 30, 50])
    lam = trial.suggest_categorical('lamdba', [0.8, 0.9, 0.92, 0.95, 0.98, 0.99, 1.0])

    if n_steps < batch_size:
        nminibatches = 1
    else:
        nminibatches = int(n_steps / batch_size)

    return {
        'n_steps': n_steps,
        'nminibatches': nminibatches,
        'gamma': gamma,
        'learning_rate': learning_rate,
        'ent_coef': ent_coef,
        'cliprange': cliprange,
        'noptepochs': noptepochs,
        'lam': lam
    }


def sample_a2c_params(trial):
    """
    Sampler for A2C hyperparams.

    :param trial: (optuna.trial)
    :return: (dict)
    """
    gamma = trial.suggest_categorical('gamma', [0.9, 0.95, 0.98, 0.99, 0.995, 0.999, 0.9999])
    n_steps = trial.suggest_categorical('n_steps', [5, 16, 32, 64])
    lr_schedule = trial.suggest_categorical('lr_schedule', ['linear', 'constant'])
    learning_rate = trial.suggest_loguniform('lr', 1e-5, 1)
    ent_coef = trial.suggest_loguniform('ent_coef', 0.00000001, 0.1)

    return {
        'n_steps': n_steps,
        'gamma': gamma,
        'learning_rate': learning_rate,
        'lr_schedule': lr_schedule,
        'ent_coef': ent_coef
    }


def sample_sac_params(trial):
    """
    Sampler for SAC hyperparams.

    :param trial: (optuna.trial)
    :return: (dict)
    """
    gamma = trial.suggest_categorical('gamma', [0.9, 0.95, 0.98, 0.99, 0.995, 0.999, 0.9999])
    learning_rate = trial.suggest_loguniform('lr', 1e-5, 1)
    batch_size = trial.suggest_categorical('batch_size', [16, 32, 64, 128, 256])
    buffer_size = trial.suggest_categorical('buffer_size', [int(1e4), int(1e5), int(1e6)])
    learning_starts = trial.suggest_categorical('learning_starts', [0, 1000, 10000, 20000])
    train_freq = trial.suggest_categorical('train_freq', [1, 100, 300])
    # gradient_steps takes too much time
    # gradient_steps = trial.suggest_categorical('gradient_steps', [1, 100, 300])
    gradient_steps = 1
    ent_coef = trial.suggest_categorical('ent_coef', ['auto', 0.5, 0.1, 0.05, 0.01, 0.0001])

    target_entropy = 'auto'
    if ent_coef == 'auto':
        target_entropy =  trial.suggest_categorical('target_entropy', ['auto', -1, -10, -20, -50, -100])

    return {
        'gamma': gamma,
        'learning_rate': learning_rate,
        'batch_size': batch_size,
        'buffer_size': buffer_size,
        'learning_starts': learning_starts,
        'train_freq': train_freq,
        'gradient_steps': gradient_steps,
        'ent_coef': ent_coef,
        'target_entropy': target_entropy
    }

def sample_trpo_params(trial):
    """
    Sampler for TRPO hyperparams.

    :param trial: (optuna.trial)
    :return: (dict)
    """
    gamma = trial.suggest_categorical('gamma', [0.9, 0.95, 0.98, 0.99, 0.995, 0.999, 0.9999])
    timesteps_per_batch = trial.suggest_categorical('timesteps_per_batch', [16, 32, 64, 128, 256, 512, 1024, 2048])
    max_kl = trial.suggest_loguniform('max_kl', 0.00000001, 1)
    ent_coef = trial.suggest_loguniform('ent_coef', 0.00000001, 0.1)
    lam = trial.suggest_categorical('lamdba', [0.8, 0.9, 0.92, 0.95, 0.98, 0.99, 1.0])
    cg_damping = trial.suggest_loguniform('cg_damping', 1e-5, 1)
    cg_iters = trial.suggest_categorical('cg_iters', [1, 10, 20, 30, 50])
    vf_stepsize = trial.suggest_loguniform('vf_stepsize', 1e-5, 1)
    vf_iters = trial.suggest_categorical('vf_iters', [1, 3, 5, 10, 20])


    return {
        'gamma': gamma,
        'timesteps_per_batch': timesteps_per_batch,
        'max_kl': max_kl,
        'entcoeff': ent_coef,
        'lam': lam,
        'cg_damping': cg_damping,
        'cg_iters': cg_iters,
        'vf_stepsize': vf_stepsize,
        'vf_iters': vf_iters
    }


HYPERPARAMS_SAMPLER = {
    'ppo2': sample_ppo2_params,
    'sac': sample_sac_params,
    'a2c': sample_a2c_params,
    'trpo': sample_trpo_params
}