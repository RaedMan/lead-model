from drain.step import Step
from drain import util, data
from drain.data import FromSQL
from lead.output import aggregations

import pandas as pd
import numpy as np
import logging

class LeadData(Step):
    EXCLUDE = {'first_name', 'last_name', 'address_residential', 
               'address'}

    PARSE_DATES = ['date_of_birth', 'first_bll6_sample_date', 
        'first_bll10_sample_date', 'first_sample_date', 
        'last_sample_date', 'min_date', 'max_date', 'wic_min_date', 
        'test_min_date', 'wic_max_date', 'test_max_date']

    AUX = {'address_count', 'age', 'wic', 'test_count', 
            'max_bll', 'mean_bll'}
    AUX.update(PARSE_DATES)


    def __init__(self, month, day, year_min=2008, **kwargs):
        Step.__init__(self, month=month, day=day, year_min=year_min, **kwargs)

        kid_addresses = FromSQL(query="""
select * from output.kids join output.kid_addresses using (kid_id)
join output.addresses using (address_id)
where date_of_birth >= '{date_min}'
""".format(date_min='%s-%s-%s' % (self.year_min, self.month, self.day)), 
                parse_dates=self.PARSE_DATES, target=True)

        self.aggregations = aggregations.all()
        self.inputs = [kid_addresses] + self.aggregations
        self.input_mapping=['X']

    def run(self, X, *args, **kwargs):
        # Date stuff
        # TODO: include people who are born and poisoned before a date
        # TODO: exclude them from test
        logging.info('dates')
        X['date'] = X.date_of_birth.apply(
                util.date_ceil(self.month, self.day))
        logging.info('more_dates')
        X['age'] = (X.date - X.date_of_birth)/util.day
        X['date_of_birth_days'] = X.date_of_birth.apply(util.date_to_days)
        X['date_of_birth_month'] = X.date_of_birth.apply(lambda d: d.month)

        # join before setting index
        for aggregation in self.aggregations:
            logging.info('Joining %s' % aggregation)
            X = aggregation.join(X)

        # Set index
        X.set_index(['kid_id', 'address_id'], inplace=True)

        # Separate aux
        aux = X[list(self.AUX)]
        X = data.select_features(X, exclude=(self.AUX | self.EXCLUDE))

        # Sample dates used for training_min_max_sample_age in LeadTransform
        # TODO: could make this more efficient
        engine = util.create_engine()
        sample_dates = pd.read_sql("""
select kid_id, sample_date, date_of_birth
from output.tests join output.kids using (kid_id)""", engine, parse_dates=['date_of_birth', 'sample_date'])
        
        return {'X':X, 'aux':aux, 'sample_dates':sample_dates}

class LeadTransform(Step):
    EXCLUDE = {'address_id', 'building_id', 'complex_id', 
            'census_block_id', 'census_tract_id', 'ward_id', 
            'community_area_id'}

    def __init__(self, month, day, year, train_years, 
            train_min_last_sample_age = 3*365, wic_sample_weight=1,
            **kwargs):
        Step.__init__(self, month=month, day=day, year=year, 
                train_years=train_years, 
                train_min_last_sample_age=train_min_last_sample_age,
                wic_sample_weight=wic_sample_weight, **kwargs)

    def run(self, X, aux, sample_dates):
        # TODO: move this into an HDFReader for efficiency
        drop = aux.date_of_birth < util.timestamp(
                self.year-self.train_years-1, self.month, self.day)
        X.drop(X.index[drop], inplace=True)
        aux.drop(aux.index[drop], inplace=True)

        logging.info('Splitting train and test sets')
        today = util.timestamp(self.month, self.day, self.year)

        # add date column to index
        X.set_index('date', append=True, inplace=True) 
        aux.index = X.index

        date = data.index_as_series(aux, 'date')

        train = date < today
        # don't include future addresses in training
        train &= (aux.wic_min_date < today) | (aux.test_min_date < today)
        # subset to potential training kids
        max_sample_ages = censor_max_sample_ages(
                X[train].index.get_level_values('kid_id'), 
                sample_dates, today)

        kids_min_max_sample_age = max_sample_ages[
                (max_sample_ages > self.train_min_last_sample_age)].index
        train &= (
                data.index_as_series(X, 'kid_id').isin(
                    kids_min_max_sample_age) |
                (aux.first_bll6_sample_date < today).fillna(False))
         
        test = data.index_as_series(X, 'date') == today
        aux.drop(aux.index[~(train | test)], inplace=True)
        X,train,test = data.train_test_subset(X, train, test)

        #logging.info('Binarizing')
        # TODO: include gender, ethnicity, etc.
        # binarize census tract
        # data.binarize(X, {'community_area_id'})
    
        # set outcome variable, censored in training
        y = aux.first_bll6_sample_date.notnull().where(
            test | (aux.first_bll6_sample_date < today), False)

        X = data.select_features(X, exclude=self.EXCLUDE)
        X = data.impute(X, train=train)

        sample_weight = 1 + (
                aux.wic_min_date.notnull() * self.wic_sample_weight)

        c = data.non_numeric_columns(X)
        if len(c) > 0:
            logging.warning('Non-numeric columns: %s' % c)

        return {'X': X.astype(np.float32), 'y': y, 
                'train': train, 'test': test, 
                'aux': aux, 'sample_weight': sample_weight}

def censor_max_sample_ages(kids, sample_dates, today):
    # get max sample age for specified kids, censoring by today
    train_sample_dates = sample_dates.kid_id.isin(kids)
    sample_dates.drop(sample_dates.index[~train_sample_dates], inplace=True)
    # calculate age
    sample_dates['age'] = (sample_dates.sample_date - sample_dates.date_of_birth)/util.day
    # find max sample age for each kid
    max_sample_ages = sample_dates.groupby('kid_id')['age'].max()
    return max_sample_ages
