# -*- coding: utf-8 -*-
"""
"""
import torch
import time
import pgbm
from sklearn.model_selection import train_test_split
import properscoring as ps
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from pgbm.datasets import get_dataset, get_fold
#%% Objective
def objective(yhat, y):
    gradient = (yhat - y)
    hessian = 1 + yhat*0.
    
    return gradient, hessian

def rmseloss_metric(yhat, y):
    loss = (yhat - y).pow(2).mean().sqrt()

    return loss

def rmseloss_metric_np(yhat, y):
    loss = np.sqrt(np.mean((yhat - y)**2))
    return loss    
#%% Generic Parameters
# PGBM specific
method = 'pgbm'
params = {'min_split_gain':0,
      'min_data_in_leaf':1,
      'max_leaves':8,
      'max_bin':64,
      'learning_rate':0.1,
      'n_estimators':100,
      'verbose':2,
      'early_stopping_rounds':2000,
      'feature_fraction':1,
      'bagging_fraction':1,
      'seed':1,
      'lambda':1,
      'tree_correlation':0.03,
      'device':'gpu',
      'output_device':'gpu',
      'gpu_device_ids':(1,),
      'derivatives':'exact',
      'distribution':'normal'}
n_samples = 1000
#%% Loop
datasets = ['msd','protein']
base_estimators = 2000
df_test = pd.DataFrame(columns=['method', 'dataset','fold','device','validation_estimators','test_estimators','rmse_test','crps_test','validation_time','max_leaves','rho'])
df_val = pd.DataFrame(columns=['method', 'dataset','fold','device','validation_estimators','test_estimators','rho','crps','max_leaves'])
torchdata = lambda x : torch.from_numpy(x).float()
max_leaves_array = [8, 32, 128]
for i, dataset in enumerate(datasets):
    for max_leaves in max_leaves_array:
        if dataset == 'msd':
            params['bagging_fraction'] = 0.1
        else:
            params['bagging_fraction'] = 1
        params['max_leaves'] = max_leaves
        # Get data
        data = get_dataset(dataset)
        X_train, X_test, y_train, y_test = get_fold(dataset, data, 0)
        X_train_val, X_val, y_train_val, y_val = train_test_split(X_train, y_train, test_size=0.2, random_state=0)
        # Build torchdata datasets
        train_data = (torchdata(X_train), torchdata(y_train))
        train_val_data = (torchdata(X_train_val), torchdata(y_train_val))
        valid_data = (torchdata(X_val), torchdata(y_val))
        test_data = (torchdata(X_test), torchdata(y_test))
        params['n_estimators'] = base_estimators
        # Train to retrieve best iteration
        print('Validating...')
        model = pgbm.PGBM(params)
        start = time.perf_counter()    
        model.train(train_val_data, objective=objective, metric=rmseloss_metric, valid_set=valid_data)
        torch.cuda.synchronize()
        end = time.perf_counter()
        validation_time = end - start
        print(f'Fold time: {validation_time:.2f}s')
        # Find best tree correlation on validation set
        tree_correlations = np.arange(-9, 10) * 0.01
        crps_pgbm = np.zeros(len(tree_correlations))
        for i, tree_correlation in enumerate(tree_correlations):
            model.params['tree_correlation'] = tree_correlation
            yhat_dist_pgbm = model.predict_dist(valid_data[0], n_samples=n_samples)
            crps_pgbm[i] = ps.crps_ensemble(y_val, yhat_dist_pgbm.cpu().T).mean()
            df_val = df_val.append({'method':method, 'dataset':dataset, 'fold':0, 'device':params['device'], 'validation_estimators': base_estimators, 'test_estimators':params['n_estimators'], 'rho': tree_correlation, 'crps_validation': crps_pgbm[i], 'max_leaves':max_leaves}, ignore_index=True)
        # Set iterations to best iteration
        params['n_estimators'] = model.best_iteration + 1
        # Retrain on full set   
        print('Training...')
        model = pgbm.PGBM(params)
        model.train(train_data, objective=objective, metric=rmseloss_metric)
        #% Predictions
        print('Prediction...')
        yhat_point_pgbm = model.predict(test_data[0])   
        model.params['tree_correlation'] = tree_correlations[np.argmin(crps_pgbm)]
        yhat_dist_pgbm = model.predict_dist(test_data[0], n_samples=n_samples)
        # Scoring
        rmse_pgbm_new = rmseloss_metric(yhat_point_pgbm.cpu(), test_data[1]).numpy()
        crps_pgbm_new = ps.crps_ensemble(y_test, yhat_dist_pgbm.cpu().T).mean()
        # Save data
        df_test = df_test.append({'method':method, 'dataset':dataset, 'fold':0, 'device':params['device'], 'validation_estimators': base_estimators, 'test_estimators':params['n_estimators'], 'rmse_test': rmse_pgbm_new, 'crps_test': crps_pgbm_new, 'validation_time':validation_time, 'max_leaves':max_leaves, 'rho':model.params['tree_correlation']}, ignore_index=True)   
#%% Save data
filename_val = "max_leaves_variation_validation.csv"
df_val.to_csv(f'pgbm/experiments/01a_rho_variation/{filename_val}')
filename_test = "max_leaves_variation_test.csv"
df_test.to_csv(f'pgbm/experiments/01a_rho_variation/{filename_test}')        
#%% Create plot
filename_val = "max_leaves_variation_validation.csv"
df_val = pd.read_csv(f'pgbm/experiments/01a_rho_variation/{filename_val}')
datasets = ['msd', 'protein']
tree_correlations = np.arange(-9, 10) * 0.01
max_leaves_array = [8, 32, 128]
best_crps = np.zeros((2, 3))
fig, ax = plt.subplots(1, 1)
for i, dataset in enumerate(datasets):
    for j, max_leaves in enumerate(max_leaves_array):
        best_crps[i, j] = df_val[(df_val['dataset'] == dataset) & (df_val['max_leaves'] == max_leaves)]['crps_validation'].min()
        ax.plot(tree_correlations, df_val[(df_val['dataset'] == dataset) & (df_val['max_leaves'] == max_leaves)]['crps_validation'] / best_crps[i, j], label=f'{dataset} ({max_leaves})')
#plt.xticks(np.arange(-9, 10, step=2) * 0.01)
ax.tick_params(axis='both', which='major', labelsize=22)
ax.set_ylim(0.99, 1.2)
ax.set_xlabel('Tree correlation', fontsize=22)
ax.set_ylabel('Normalized CRPS', fontsize=22)
handles, labels = ax.get_legend_handles_labels()
leg = fig.legend(handles, labels, loc = 'lower center', ncol=3, fontsize=22)
leg.get_frame().set_linewidth(0.0)