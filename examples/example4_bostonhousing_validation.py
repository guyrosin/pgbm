"""
   Copyright (c) 2021 Olivier Sprangers 

   Licensed under the Apache License, Version 2.0 (the "License");
   you may not use this file except in compliance with the License.
   You may obtain a copy of the License at

       http://www.apache.org/licenses/LICENSE-2.0

   Unless required by applicable law or agreed to in writing, software
   distributed under the License is distributed on an "AS IS" BASIS,
   WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
   See the License for the specific language governing permissions and
   limitations under the License.

   https://github.com/elephaint/pgbm/blob/main/LICENSE

"""

#%% Load packages
import torch
import pgbm
from sklearn.model_selection import train_test_split
from sklearn.datasets import load_boston
import matplotlib.pyplot as plt
#%% Objective for pgbm
def mseloss_objective(yhat, y):
    gradient = (yhat - y)
    hessian = torch.ones_like(yhat)

    return gradient, hessian

def rmseloss_metric(yhat, y):
    loss = (yhat - y).pow(2).mean().sqrt()

    return loss
#%% Load data
X, y = load_boston(return_X_y=True)
#%% Parameters
params = {'min_split_gain':0,
      'min_data_in_leaf':1,
      'max_leaves':8,
      'max_bin':64,
      'learning_rate':0.1,
      'n_estimators':2000,
      'verbose':2,
      'early_stopping_rounds':100,
      'feature_fraction':1,
      'bagging_fraction':1,
      'seed':1,
      'lambda':1,
      'tree_correlation':0.03,
      'device':'gpu',
      'output_device':'gpu',
      'gpu_device_ids':(0,),
      'derivatives':'exact',
      'distribution':'normal'}

n_samples = 1000
n_splits = 2
base_estimators = 2000
#%% Validation loop
torchdata = lambda x : torch.from_numpy(x).float()
rmse, crps = torch.zeros(n_splits), torch.zeros(n_splits)
for i in range(n_splits):
    print(f'Fold {i+1}/{n_splits}')
    # Split for model validation
    X_train, X_test, y_train, y_test = train_test_split(X, y, test_size=0.1, random_state=i)
    X_train_val, X_val, y_train_val, y_val = train_test_split(X_train, y_train, test_size=0.2, random_state=i)
    # Build torchdata datasets
    train_data = (torchdata(X_train), torchdata(y_train))
    train_val_data = (torchdata(X_train_val), torchdata(y_train_val))
    valid_data = (torchdata(X_val), torchdata(y_val))
    test_data = (torchdata(X_test), torchdata(y_test))
    # Train to retrieve best iteration
    print('PGBM Validating on partial dataset...')
    params['n_estimators'] = base_estimators
    model = pgbm.PGBM(params)
    model.train(train_val_data, objective=mseloss_objective, metric=rmseloss_metric, valid_set=valid_data)
    # Set iterations to best iteration
    params['n_estimators'] = model.best_iteration + 1
    # Retrain on full set   
    print('PGBM Training on full dataset...')
    model = pgbm.PGBM(params)
    model.train(train_data, objective=mseloss_objective, metric=rmseloss_metric)
    #% Predictions
    print('PGBM Prediction...')
    yhat_point_pgbm = model.predict(test_data[0])
    yhat_dist_pgbm = model.predict_dist(test_data[0], n_samples=n_samples)
    # Scoring
    rmse[i] = rmseloss_metric(yhat_point_pgbm.cpu(), test_data[1])
    crps[i] = pgbm.crps_ensemble(test_data[1], yhat_dist_pgbm.cpu()).mean()           
    # Print scores current fold
    print(f'RMSE Fold {i+1}, {rmse[i]:.2f}')
    print(f'CRPS Fold {i+1}, {crps[i]:.2f}')
      
# Print final scores
print(f'RMSE {rmse.mean():.2f}+-{rmse.std():.2f}')
print(f'CRPS {crps.mean():.2f}+-{crps.std():.2f}')
#%% Plot all samples
plt.plot(test_data[1], 'o', label='Actual')
plt.plot(yhat_point_pgbm.cpu(), 'ko', label='Point prediction PGBM')
plt.plot(yhat_dist_pgbm.cpu().max(dim=0).values, 'k--', label='Max bound PGBM')
plt.plot(yhat_dist_pgbm.cpu().min(dim=0).values, 'k--', label='Min bound PGBM')
plt.legend()