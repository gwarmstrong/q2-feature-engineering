from imblearn import combine
from qiime2.plugin import (Str, Int)
import biom
from q2_feature_engineering._tada.logger import LOG
from qiime2 import NumericMetadataColumn
import numpy as np
import pandas as pd
import qiime2

dispatcher = {'SMOTEENN': combine.SMOTEENN, 'SMOTETomek': combine.SMOTETomek}


def _sort_metada(targets_metadata, biom_table):
    targets = targets_metadata.to_dataframe()

    # filter features and targest so samples match
    index = set(targets.index)
    index = [ix for ix in biom_table.ids('sample') if ix in index]
    targets = targets.loc[index]
    feature_data = biom_table.filter(index, inplace=False)
    return targets, feature_data


def _read_inputs(biom_table: biom.Table, meta_data: NumericMetadataColumn = None):
    if meta_data:
        meta, biom_table = _sort_metada(meta_data, biom_table)
        y = meta.iloc[:, 0]
        samples = meta.index
    else:
        samples = biom_table.ids('sample')
        y = pd.DataFrame(data=np.asarray(np.ones((len(samples), 1))).ravel(), index=samples)

    _table = biom_table.sort_order(axis='sample', order=samples)

    if np.sum(samples != _table.ids('sample')) > 0:
        raise ValueError("The samples IDs in meta data and biom table are not the same! The difference is:",
                         set(samples) - set(_table.ids('sample')), "Please double check.")

    return _table, y


def synthetic_over_sampling(table: biom.Table, metadata: NumericMetadataColumn,
                            concatenate_meta: Str, method: Str = 'SMOTETomek',
                            k_neighbors: Int = 5, m_neighbors: Int = 10, n_jobs: Int = 1,
                            log_fp: Str = None, sampling_strategy: Str = 'auto',
                            random_state: Int = 42, output_log_fp: Str = None) -> biom.Table:
    if log_fp:
        logger_ins = LOG(log_fp=log_fp).get_logger('synthetic_sampling_combination')
        logger_ins.info("The parameters used for oversampling are")
        logger_ins.info('k_neighbors:', k_neighbors)
        logger_ins.info('m_neighbors:', m_neighbors)
        logger_ins.info('Sampling method:', method)
        logger_ins.info('Output log file path:', log_fp)
        logger_ins.info('sampling_strategy:', sampling_strategy)
        logger_ins.info('n_jobs:', n_jobs)
        logger_ins.info('random_state:', random_state)

    cls = dispatcher[method]
    if method != 'RandomOverSampler':
        table.norm(inplace=True)
        if log_fp:
            logger_ins.info("The input table is normalized before using it for oversampling")
    sorted_table, sorted_metadata = _read_inputs(table, meta_data=metadata)
    matrix_data = sorted_table.matrix_data.transpose()
    if method not in dispatcher:
        raise ValueError(
            'The optional methods for over sampling are', dispatcher.keys(), "instead it received", method
        )
    if method == 'ADASYN':
        over_sampling_cls = cls(sampling_strategy=sampling_strategy,
                                random_state=random_state, n_neighbors=k_neighbors, n_jobs=n_jobs)
    elif method == 'RandomOverSampler':
        over_sampling_cls = cls(sampling_strategy=sampling_strategy, random_state=random_state)
    else:
        over_sampling_cls = cls(sampling_strategy=sampling_strategy, m_neighbors=m_neighbors,
                                random_state=random_state, n_jobs=n_jobs, k_neighbors=k_neighbors)
    X_resampled, y_resampled = over_sampling_cls.fit_resample(matrix_data, sorted_metadata)
    if np.sum(np.abs(X_resampled[:len(matrix_data), :] - matrix_data)) != 0 or \
            np.sum(y_resampled[:len(matrix_data)] == metadata) != len(matrix_data):
        raise ValueError(
            "Over sampling method changed the data! Please double check your biom table"
        )
    else:
        if log_fp:
            logger_ins.info("The oversampling finished successfully!")
            logger_ins.info("The first", len(matrix_data), "samples belong to the original training samples and the "
                                                           "next", len(X_resampled) - len(matrix_data),
                            "samples belong to the new ones")
            logger_ins.info("Overall, the size of data is", len(X_resampled))
    if method != 'RandomOverSampler':
        dummy_samples = np.asarray(list(sorted_table.ids('sample')) +
                                   ["dummy_sample_" + str(i) for i in range(len(X_resampled) - len(matrix_data))])
    else:
        dummy_samples = over_sampling_cls.sample_indices_

    oversampled_table = biom.Table(X_resampled, observation_ids=sorted_table.ids('observation'),
                                   sample_ids=dummy_samples)
    oversampled_metadata = pd.DataFrame(index=dummy_samples, data=y_resampled)
    oversampled_metadata.index.names = ['#SampleID']
    oversampled_metadata.columns = ['label']
    oversampled_meta = qiime2.Metadata(oversampled_metadata)
    oversampled_meta.save()

    return oversampled_table
