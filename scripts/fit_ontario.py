import os
import sys
import numpy as np
import matplotlib.pyplot as plt
import torch
import datetime as dt
import csv
import pymongo

############### Paths ##############################
####################################################

# modified from fit_bexar.py for testing purposes
ROOT_DIR = os.path.join(os.path.dirname(__file__), '..')
sys.path.append(ROOT_DIR)

WEIGHTS_DIR = os.path.join(ROOT_DIR, 'model_weights')
if not os.path.exists(WEIGHTS_DIR):
  os.mkdir(WEIGHTS_DIR)

RESULTS_DIR = os.path.join(ROOT_DIR, 'Prediction_results')
if not os.path.exists(RESULTS_DIR):
  os.mkdir(RESULTS_DIR)

from SIRNet import util, trainer
from scripts import retrieve_data

########### ASSUMPTIONS ##############################
######################################################
reporting_rate = 0.1  # Portion of cases that are actually detected
delay_days = 10  # Days between becoming infected / positive confirmation (due to incubation period / testing latency
start_model = 23  # The day where we begin our fit

client = pymongo.MongoClient("mongodb+srv://Jeremy:<password>@cluster0.ptx5w.mongodb.net/covid?retryWrites=true&w=majority")
# client = pymongo.MongoClient("mongodb://localhost:27017/")
db = client["covid"]
collection = db['csv']

# only support single-region for now (due to reopening diff)
def train_and_forecast(provinces):
  ############## Simplified Data ####################
  ###################################################
  paramdict = {}
  paramdict['country'] = 'Canada'
  paramdict['states'] = provinces
  paramdict['counties'] = None
  region_name = 'Ontario'

  # paramdict['counties'] = ['Bexar County']
  df = retrieve_data.get_data(paramdict)

  # mobility = df[['Retail & recreation', 'Grocery & pharmacy', 'Parks',
  #                'Transit stations', 'Workplace', 'Residential']]
  stage_mobility = retrieve_data.retrieve_stage_mobility(paramdict)

  populations = retrieve_data.load_canada_pop_data(paramdict)

  # todo: generalize this for training all regions in Canada
  population = populations[0]

  case_data = retrieve_data.get_case_data_JHP(paramdict)

  ini_date_str = "1/22/20"
  if len(ini_date_str.split("/")[0]) == 1:
    ini_date = dt.datetime.strptime("0" + ini_date_str, "%m/%d/%y")
  else:
    ini_date = dt.datetime.strptime(ini_date_str, "%m/%d/%y")

  cases = []
  no_case = True
  for state in paramdict['states']:
    state_case = case_data.loc[case_data['Province/State'] == state]
    state_case = state_case.reset_index()
    while ini_date_str in case_data.columns:
      if not (state_case[ini_date_str][0] == 0 and no_case):
        # first case(s)
        if state_case[ini_date_str][0] > 0 and no_case:
          day0 = ini_date_str
          day0_dt = ini_date
          no_case = False
        cases.append(state_case[ini_date_str][0])

      ini_date += dt.timedelta(days=1)

      # reformat dates
      new_date = ini_date.strftime("%x")

      if new_date[0] == "0":
        new_date = ini_date.strftime("%x")[1:]
      if len(new_date.split("/")[1]) == 2 and new_date.split("/")[1][0] == '0':
        new_date = new_date.split("/")[0]+"/"+new_date.split("/")[1][1]+"/"+new_date.split("/")[2]
      ini_date_str = new_date

  #first case date does not exist in mobility data
  if len(df.index[df["date"] == day0_dt.strftime("%Y-%m-%d")].tolist()) == 0:
    ini_mobi_date = dt.datetime.strptime(df["date"][0], "%Y-%m-%d")
    delta = (ini_mobi_date - day0_dt).days
    cases = cases[20:]

  # index_day0 = df.index[df["date"] == day0_dt.strftime("%Y-%m-%d")].tolist()[0]
  df = df.dropna(axis=0, subset=["retail_and_recreation_percent_change_from_baseline"])

  mobility = df[
    ['retail_and_recreation_percent_change_from_baseline', 'grocery_and_pharmacy_percent_change_from_baseline',
     'parks_percent_change_from_baseline', 'transit_stations_percent_change_from_baseline',
     'workplaces_percent_change_from_baseline', 'residential_percent_change_from_baseline']]


  # offset case data by delay days (treat it as though it was recorded earlier)
  if len(cases) > len(mobility):
    diff = len(cases)-len(mobility)
    if diff < delay_days:
      cases = np.array(cases[delay_days:])
      mobility = np.array(mobility[:-(delay_days-diff)])
    else:
      cases = cases[:-(delay_days-diff)]
      cases = np.array(cases[delay_days:])
      mobility = np.array(mobility)

  # offset case data by delay days (treat it as though it was recorded earlier)
  # cases = np.array(cases[delay_days:])
  # mobility = np.array(mobility[:-delay_days])

  ###################### Formatting Data ######################
  #############################################################
  mobility = np.asarray(mobility, dtype=np.float32)
  # convert percentages of change to fractions of activity
  mobility[:, :6] = (1.0 + mobility[:, :6] / 100.0)

  # Initial conditions
  i0 = float(cases[start_model - 1]) / population / reporting_rate
  e0 = 2.2 * i0 / 5.0
  mobility = mobility[start_model:]  # start with delay
  cases = cases[start_model:]  # delay days

  # Split into input and output data
  X, Y = mobility, cases

  # divide out population of county, reporting rate
  Y = (Y / population) / reporting_rate

  # To Torch on device
  X = torch.from_numpy(X.astype(np.float32))
  Y = torch.from_numpy(Y.astype(np.float32))

  # Add batch dimension
  X = X.reshape(X.shape[0], 1, X.shape[1])  # time x batch x channels
  Y = Y.reshape(Y.shape[0], 1, 1)  # time x batch x channels

  #################### Training #######################
  #####################################################
  weights_name = WEIGHTS_DIR + '/{}_weights.pt'.format(region_name)
  trainer_ = trainer.Trainer(weights_name)
  model = trainer_.build_model(e0, i0)
  trainer_.train(model, X, Y, 300)

  ################ Forecasting #######################
  ####################################################
  active = {}
  total = {}
  stage_mobility[25] = "25%"
  stage_mobility[50] = "50%"
  stage_mobility[75] = "75%"
  stage_mobility[100] = "100%"

  cases = stage_mobility.keys()

  for case in cases:
    xN = torch.ones((1, 6), dtype=torch.float32) * case / 100
    rX = xN.expand(200, *xN.shape)  # 200 x 1 x 6
    rX = torch.cat((X, rX), dim=0)
    sir_state, total_cases = model(rX)
    s = util.to_numpy(sir_state)
    active[case] = s[:, 0] * reporting_rate * population
    total[case] = (s[:, 0] + s[:, 1]) * reporting_rate * population

  ############## Forecast Dates ####################
  ##################################################
  #yy, mm, dd = day0.split('-')
  mm, dd, yy = day0.split('/')
  date0 = dt.datetime(int(yy), int(mm), int(dd))
  days = np.arange(rX.shape[0])
  dates = [date0 + dt.timedelta(days=int(d + delay_days + start_model))
           for d in days]

  ############### Reporting #########################
  ###################################################
  print('\n#########################################\n\n')
  timestamp = dt.datetime.now().strftime('%Y_%m_%d')

  os.chdir('../Prediction_results')

  for case in cases:
    newcsv = {
      "case": stage_mobility[case],
      "country": paramdict['country'],
      "province": paramdict['states'][0],
      "filename": stage_mobility[case]+"_"+paramdict['country']+"_"+paramdict['states'][0]+".csv"
    }
    if (collection.find(newcsv).count() < 0):
      collection.insert_one(newcsv)

    with open(stage_mobility[case]+"_"+paramdict['country']+"_"+paramdict['states'][0]+".csv", "w", newline='') as csv_file:
      wr = csv.writer(csv_file, quoting=csv.QUOTE_ALL)
      wr.writerow(dates)
      wr.writerow(active[case])

    M = np.max(active[case])
    idx = np.argmax(active[case])
    print('Case: {}%'.format(case))
    print('  Max value: {}'.format(M))
    print('  Day: {}, {}'.format(idx, dates[idx]))

# train_and_forecast(['Ontario'], ['Toronto Division'])
# train_and_forecast(['Ontario'], ['Timiskaming District'])
train_and_forecast(['Ontario'])

