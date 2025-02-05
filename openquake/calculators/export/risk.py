# -*- coding: utf-8 -*-
# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright (C) 2014-2017 GEM Foundation
#
# OpenQuake is free software: you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License as published
# by the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# OpenQuake is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with OpenQuake. If not, see <http://www.gnu.org/licenses/>.
from __future__ import division
import itertools
import collections
import logging
import numpy

from openquake.baselib import hdf5, parallel, performance
from openquake.baselib.python3compat import decode, encode
from openquake.baselib.general import (
    group_array, split_in_blocks, deprecated as depr)
from openquake.hazardlib.stats import compute_stats2
from openquake.risklib import scientific, riskinput
from openquake.calculators.export import export, loss_curves
from openquake.calculators.export.hazard import savez
from openquake.commonlib import writers, calc
from openquake.commonlib.util import (
    get_assets, compose_arrays, reader)

Output = collections.namedtuple('Output', 'ltype path array')
F32 = numpy.float32
F64 = numpy.float64
U16 = numpy.uint16
U32 = numpy.uint32
U64 = numpy.uint64
stat_dt = numpy.dtype([('mean', F32), ('stddev', F32)])


deprecated = depr('Use the csv exporter instead')


def add_quotes(values):
    # used to escape tags in CSV files
    return numpy.array([encode('"%s"' % val) for val in values], (bytes, 100))


def get_rup_data(ebruptures):
    dic = {}
    for ebr in ebruptures:
        point = ebr.rupture.surface.get_middle_point()
        dic[ebr.serial] = (ebr.rupture.mag, point.x, point.y, point.z)
    return dic

# ############################### exporters ############################## #


# this is used by event_based_risk
@export.add(('agg_curves-rlzs', 'csv'), ('agg_curves-stats', 'csv'))
def export_agg_curve_rlzs(ekey, dstore):
    oq = dstore['oqparam']
    agg_curve = dstore[ekey[0]]
    periods = dstore.get_attr(ekey[0], 'return_periods')
    if ekey[0].endswith('stats'):
        tags = ['mean'] + ['quantile-%s' % q for q in oq.quantile_loss_curves]
    else:
        tags = ['rlz-%03d' % r for r in range(agg_curve.shape[1])]
    writer = writers.CsvWriter(fmt=writers.FIVEDIGITS)
    header = (('annual_frequency_of_exceedence', 'return_period') +
              agg_curve.dtype.names)
    for r, tag in enumerate(tags):
        d = compose_arrays(periods, agg_curve[:, r], 'return_period')
        data = compose_arrays(1 / periods, d, 'annual_frequency_of_exceedence')
        dest = dstore.build_fname('agg_loss', tag, 'csv')
        writer.save(data, dest, header)
    return writer.getsaved()


# this is used by event_based_risk and classical_risk
@export.add(('avg_losses-rlzs', 'csv'), ('avg_losses-stats', 'csv'))
def export_avg_losses(ekey, dstore):
    """
    :param ekey: export key, i.e. a pair (datastore key, fmt)
    :param dstore: datastore object
    """
    dskey = ekey[0]
    oq = dstore['oqparam']
    dt = oq.loss_dt()
    assets = get_assets(dstore)
    writer = writers.CsvWriter(fmt=writers.FIVEDIGITS)
    name, kind = dskey.split('-')
    if kind == 'stats':
        weights = dstore['realizations']['weight']
        tags, stats = zip(*oq.risk_stats())
        if dskey in dstore:  # precomputed
            value = dstore[dskey].value
        else:  # computed on the fly
            value = compute_stats2(
                dstore['avg_losses-rlzs'].value, stats, weights)
    else:  # rlzs
        value = dstore[dskey].value  # shape (A, R, LI)
        R = value.shape[1]
        tags = ['rlz-%03d' % r for r in range(R)]
    for tag, values in zip(tags, value.transpose(1, 0, 2)):
        dest = dstore.build_fname(name, tag, 'csv')
        array = numpy.zeros(len(values), dt)
        for l, lt in enumerate(dt.names):
            array[lt] = values[:, l]
        writer.save(compose_arrays(assets, array), dest)
    return writer.getsaved()


# this is used by scenario_risk
@export.add(('losses_by_asset', 'csv'))
def export_losses_by_asset(ekey, dstore):
    """
    :param ekey: export key, i.e. a pair (datastore key, fmt)
    :param dstore: datastore object
    """
    loss_dt = dstore['oqparam'].loss_dt(stat_dt)
    losses_by_asset = dstore[ekey[0]].value
    rlzs = dstore['csm_info'].get_rlzs_assoc().realizations
    assets = get_assets(dstore)
    writer = writers.CsvWriter(fmt=writers.FIVEDIGITS)
    for rlz in rlzs:
        losses = losses_by_asset[:, rlz.ordinal]
        dest = dstore.build_fname('losses_by_asset', rlz, 'csv')
        data = compose_arrays(assets, losses.copy().view(loss_dt)[:, 0])
        writer.save(data, dest)
    return writer.getsaved()


# this is used by scenario_risk
@export.add(('losses_by_event', 'csv'))
def export_losses_by_event(ekey, dstore):
    """
    :param ekey: export key, i.e. a pair (datastore key, fmt)
    :param dstore: datastore object
    """
    loss_dt = dstore['oqparam'].loss_dt()
    all_losses = dstore[ekey[0]].value
    rlzs = dstore['csm_info'].get_rlzs_assoc().realizations
    writer = writers.CsvWriter(fmt=writers.FIVEDIGITS)
    for rlz in rlzs:
        dest = dstore.build_fname('losses_by_event', rlz, 'csv')
        data = all_losses[:, rlz.ordinal].copy().view(loss_dt)
        writer.save(data, dest)
    return writer.getsaved()


@export.add(('losses_by_asset', 'npz'))
def export_losses_by_asset_npz(ekey, dstore):
    """
    :param ekey: export key, i.e. a pair (datastore key, fmt)
    :param dstore: datastore object
    """
    loss_dt = dstore['oqparam'].loss_dt()
    losses_by_asset = dstore[ekey[0]].value
    rlzs = dstore['csm_info'].get_rlzs_assoc().realizations
    assets = get_assets(dstore)
    dic = {}
    for rlz in rlzs:
        # I am exporting the 'mean' and ignoring the 'stddev'
        losses = losses_by_asset[:, rlz.ordinal]['mean'].copy()  # shape (N, 1)
        data = compose_arrays(assets, losses.view(loss_dt)[:, 0])
        dic['rlz-%03d' % rlz.ordinal] = data
    fname = dstore.export_path('%s.%s' % ekey)
    savez(fname, **dic)
    return [fname]


def _compact(array):
    # convert an array of shape (a, e) into an array of shape (a,)
    dt = array.dtype
    a, e = array.shape
    lst = []
    for name in dt.names:
        lst.append((name, (dt[name], e)))
    return array.view(numpy.dtype(lst)).reshape(a)


# used by scenario_risk
@export.add(('all_losses-rlzs', 'npz'))
def export_all_losses_npz(ekey, dstore):
    rlzs = dstore['csm_info'].get_rlzs_assoc().realizations
    assets = get_assets(dstore)
    losses = dstore['all_losses-rlzs']
    dic = {}
    for rlz in rlzs:
        rlz_losses = _compact(losses[:, :, rlz.ordinal])
        data = compose_arrays(assets, rlz_losses)
        dic['all_losses-%03d' % rlz.ordinal] = data
    fname = dstore.build_fname('all_losses', 'rlzs', 'npz')
    savez(fname, **dic)
    return [fname]


# this is used by event_based_risk
@export.add(('agg_loss_table', 'csv'))
@depr('This exporter will be removed soon')
def export_agg_losses_ebr(ekey, dstore):
    """
    :param ekey: export key, i.e. a pair (datastore key, fmt)
    :param dstore: datastore object
    """
    if 'ruptures' not in dstore:
        logging.warn('There are no ruptures in the datastore')
        return []
    name, ext = export.keyfunc(ekey)
    agg_losses = dstore[name]
    has_rup_data = 'ruptures' in dstore
    extra_list = [('magnitude', F32),
                  ('centroid_lon', F32),
                  ('centroid_lat', F32),
                  ('centroid_depth', F32)] if has_rup_data else []
    oq = dstore['oqparam']
    lti = oq.lti
    dtlist = ([('event_id', U64), ('rup_id', U32), ('year', U32),
               ('rlzi', U16)] + extra_list + oq.loss_dt_list())
    elt_dt = numpy.dtype(dtlist)
    elt = numpy.zeros(len(agg_losses), elt_dt)
    writer = writers.CsvWriter(fmt=writers.FIVEDIGITS)
    the_events = dstore['events'].value
    all_events = group_array(the_events, 'grp_id')
    rup_data = {}
    event_by_eid = {}  # eid -> event
    # populate rup_data and event_by_eid
    ruptures_by_grp = calc.get_ruptures_by_grp(dstore)
    # TODO: avoid reading the events twice
    for grp_id, events in all_events.items():
        for event in events:
            event_by_eid[event['eid']] = event
        if has_rup_data:
            ruptures = ruptures_by_grp.get(grp_id, [])
            rup_data.update(get_rup_data(ruptures))
    for r, row in enumerate(agg_losses):
        rec = elt[r]
        event = event_by_eid[row['eid']]
        rec['event_id'] = event['eid']
        rec['year'] = event['year']
        rec['rlzi'] = row['rlzi']
        if rup_data:
            rec['rup_id'] = rup_id = event['rup_id']
            (rec['magnitude'], rec['centroid_lon'], rec['centroid_lat'],
             rec['centroid_depth']) = rup_data[rup_id]
        for lt, i in lti.items():
            rec[lt] = row['loss'][i]
    elt.sort(order=['year', 'event_id', 'rlzi'])
    dest = dstore.build_fname('agg_losses', 'all', 'csv')
    writer.save(elt, dest)
    return writer.getsaved()


# this is used by classical_risk and event_based_risk
@export.add(('loss_curves', 'csv'))
def export_loss_curves(ekey, dstore):
    if '/' not in ekey[0]:  # full loss curves are not exportable
        logging.error('Use the command oq export loss_curves/rlz-0 to export '
                      'the first realization')
        return []
    what = ekey[0].split('/', 1)[1]
    return loss_curves.LossCurveExporter(dstore).export('csv', what)


# this is used by classical_risk and event_based_risk
@export.add(('loss_curves-stats', 'csv'))
def export_loss_curves_stats(ekey, dstore):
    num_rlzs = len(dstore['realizations'])
    kind = 'stats' if num_rlzs > 1 else 'rlzs'
    return export_loss_curves(('loss_curves/' + kind, 'csv'), dstore)


# used by classical_risk and event_based_risk
@export.add(('loss_maps-rlzs', 'csv'), ('loss_maps-stats', 'csv'))
def export_loss_maps_csv(ekey, dstore):
    kind = ekey[0].split('-')[1]  # rlzs or stats
    assets = get_assets(dstore)
    value = get_loss_maps(dstore, kind)
    if kind == 'rlzs':
        tags = dstore['csm_info'].get_rlzs_assoc().realizations
    else:
        oq = dstore['oqparam']
        tags = ['mean'] + ['quantile-%s' % q for q in oq.quantile_loss_curves]
    writer = writers.CsvWriter(fmt=writers.FIVEDIGITS)
    for tag, values in zip(tags, value.T):
        fname = dstore.build_fname('loss_maps', tag, ekey[1])
        writer.save(compose_arrays(assets, values), fname)
    return writer.getsaved()


# used by classical_risk and event_based_risk
@export.add(('loss_maps-rlzs', 'npz'), ('loss_maps-stats', 'npz'))
def export_loss_maps_npz(ekey, dstore):
    kind = ekey[0].split('-')[1]  # rlzs or stats
    assets = get_assets(dstore)
    value = get_loss_maps(dstore, kind)
    R = len(dstore['realizations'])
    if kind == 'rlzs':
        tags = ['rlz-%03d' % r for r in range(R)]
    else:
        oq = dstore['oqparam']
        tags = ['mean'] + ['quantile-%s' % q for q in oq.quantile_loss_curves]
    fname = dstore.export_path('%s.%s' % ekey)
    dic = {}
    for tag, values in zip(tags, value.T):
        dic[tag] = compose_arrays(assets, values)
    savez(fname, **dic)
    return [fname]


@export.add(('damages-rlzs', 'csv'), ('damages-stats', 'csv'))
def export_damages_csv(ekey, dstore):
    rlzs = dstore['csm_info'].get_rlzs_assoc().realizations
    oq = dstore['oqparam']
    assets = get_assets(dstore)
    value = dstore[ekey[0]].value  # matrix N x R or T x R
    writer = writers.CsvWriter(fmt=writers.FIVEDIGITS)
    if ekey[0].endswith('stats'):
        tags = ['mean'] + ['quantile-%s' % q for q in oq.quantile_loss_curves]
    else:
        tags = ['rlz-%03d' % r for r in range(len(rlzs))]
    for tag, values in zip(tags, value.T):
        fname = dstore.build_fname('damages', tag, ekey[1])
        writer.save(compose_arrays(assets, values), fname)
    return writer.getsaved()


def build_damage_dt(dstore, mean_std=True):
    """
    :param dstore: a datastore instance
    :param mean_std: a flag (default True)
    :returns:
       a composite dtype loss_type -> (mean_ds1, stdv_ds1, ...) or
       loss_type -> (ds1, ds2, ...) depending on the flag mean_std
    """
    damage_states = dstore.get_attr('composite_risk_model', 'damage_states')
    dt_list = []
    for ds in damage_states:
        ds = str(ds)
        if mean_std:
            dt_list.append(('%s_mean' % ds, F32))
            dt_list.append(('%s_stdv' % ds, F32))
        else:
            dt_list.append((ds, F32))
    damage_dt = numpy.dtype(dt_list)
    loss_types = dstore.get_attr('composite_risk_model', 'loss_types')
    return numpy.dtype([(str(lt), damage_dt) for lt in loss_types])


def build_damage_array(data, damage_dt):
    """
    :param data: an array of length N with fields 'mean' and 'stddev'
    :param damage_dt: a damage composite data type loss_type -> states
    :returns: a composite array of length N and dtype damage_dt
    """
    L = len(data) if data.shape else 1
    dmg = numpy.zeros(L, damage_dt)
    for lt in damage_dt.names:
        for i, ms in numpy.ndenumerate(data[lt]):
            if damage_dt[lt].names[0].endswith('_mean'):
                lst = []
                for m, s in zip(ms['mean'], ms['stddev']):
                    lst.append(m)
                    lst.append(s)
                dmg[lt][i] = tuple(lst)
            else:
                dmg[lt][i] = ms['mean']
    return dmg


@export.add(('dmg_by_asset', 'csv'))
def export_dmg_by_asset_csv(ekey, dstore):
    damage_dt = build_damage_dt(dstore)
    rlzs = dstore['csm_info'].get_rlzs_assoc().realizations
    data = dstore[ekey[0]]
    writer = writers.CsvWriter(fmt='%.6E')
    assets = get_assets(dstore)
    for rlz in rlzs:
        dmg_by_asset = build_damage_array(data[:, rlz.ordinal], damage_dt)
        fname = dstore.build_fname(ekey[0], rlz, ekey[1])
        writer.save(compose_arrays(assets, dmg_by_asset), fname)
    return writer.getsaved()


@export.add(('dmg_by_asset', 'npz'))
def export_dmg_by_asset_npz(ekey, dstore):
    damage_dt = build_damage_dt(dstore)
    rlzs = dstore['csm_info'].get_rlzs_assoc().realizations
    data = dstore[ekey[0]]
    assets = get_assets(dstore)
    dic = {}
    for rlz in rlzs:
        dmg_by_asset = build_damage_array(data[:, rlz.ordinal], damage_dt)
        dic['rlz-%03d' % rlz.ordinal] = compose_arrays(assets, dmg_by_asset)
    fname = dstore.export_path('%s.%s' % ekey)
    savez(fname, **dic)
    return [fname]


@export.add(('dmg_by_tag', 'csv'))
@depr('This output will be removed soon')
def export_dmg_by_tag_csv(ekey, dstore):
    damage_dt = build_damage_dt(dstore)
    tags = add_quotes(dstore['assetcol'].tags())
    rlzs = dstore['csm_info'].get_rlzs_assoc().realizations
    data = dstore[ekey[0]]
    writer = writers.CsvWriter(fmt='%.6E')
    for rlz in rlzs:
        dmg_by_tag = build_damage_array(data[:, rlz.ordinal], damage_dt)
        fname = dstore.build_fname(ekey[0], rlz, ekey[1])
        array = compose_arrays(tags, dmg_by_tag, 'tag')
        writer.save(array, fname)
    return writer.getsaved()


@export.add(('dmg_total', 'csv'))
@depr('This output will be removed soon')
def export_dmg_totalcsv(ekey, dstore):
    damage_dt = build_damage_dt(dstore)
    rlzs = dstore['csm_info'].get_rlzs_assoc().realizations
    dset = dstore[ekey[0]]
    writer = writers.CsvWriter(fmt='%.6E')
    for rlz in rlzs:
        dmg_total = build_damage_array(dset[rlz.ordinal], damage_dt)
        fname = dstore.build_fname(ekey[0], rlz, ekey[1])
        data = [['loss_type', 'damage_state', 'damage_value']]
        for loss_type in dmg_total.dtype.names:
            tot = dmg_total[loss_type]
            for name in tot.dtype.names:
                data.append((loss_type, name, tot[name]))
        writer.save(data, fname)
    return writer.getsaved()


# emulate a Django point
class Location(object):
    def __init__(self, x, y):
        self.x, self.y = x, y
        self.wkt = 'POINT(%s %s)' % (x, y)


def indices(*sizes):
    return itertools.product(*map(range, sizes))


def get_loss_maps(dstore, kind):
    """
    :param dstore: a DataStore instance
    :param kind: 'rlzs' or 'stats'
    """
    oq = dstore['oqparam']
    name = 'loss_maps-%s' % kind
    if name in dstore:  # event_based risk
        return dstore[name].value.view(oq.loss_maps_dt())
    name = 'loss_curves-%s' % kind
    if name in dstore:  # classical_risk
        loss_curves = dstore[name]
        loss_maps = scientific.broadcast(
            scientific.loss_maps, loss_curves, oq.conditional_loss_poes)
        return loss_maps
    raise KeyError('loss_maps/loss_curves missing in %s' % dstore)


agg_dt = numpy.dtype([('unit', (bytes, 6)), ('mean', F32), ('stddev', F32)])


# this is used by scenario_risk
@export.add(('agglosses-rlzs', 'csv'))
def export_agglosses(ekey, dstore):
    oq = dstore['oqparam']
    loss_dt = oq.loss_dt()
    cc = dstore['assetcol/cost_calculator']
    unit_by_lt = cc.units
    unit_by_lt['occupants'] = 'people'
    agglosses = dstore[ekey[0]]
    fnames = []
    for rlz in dstore['csm_info'].get_rlzs_assoc().realizations:
        loss = agglosses[rlz.ordinal]
        losses = []
        header = ['loss_type', 'unit', 'mean', 'stddev']
        for l, lt in enumerate(loss_dt.names):
            unit = unit_by_lt[lt.replace('_ins', '')]
            mean = loss[l]['mean']
            stddev = loss[l]['stddev']
            losses.append((lt, unit, mean, stddev))
        dest = dstore.build_fname('agglosses', rlz, 'csv')
        writers.write_csv(dest, losses, header=header)
        fnames.append(dest)
    return sorted(fnames)


AggCurve = collections.namedtuple(
    'AggCurve', ['losses', 'poes', 'average_loss', 'stddev_loss'])


def get_paths(rlz):
    """
    :param rlz:
        a logic tree realization (composite or simple)
    :returns:
        a dict {'source_model_tree_path': string, 'gsim_tree_path': string}
    """
    dic = {}
    if hasattr(rlz, 'sm_lt_path'):  # composite realization
        dic['source_model_tree_path'] = '_'.join(rlz.sm_lt_path)
        dic['gsim_tree_path'] = '_'.join(rlz.gsim_lt_path)
    else:  # simple GSIM realization
        dic['source_model_tree_path'] = ''
        dic['gsim_tree_path'] = '_'.join(rlz.lt_path)
    return dic


@export.add(('bcr-rlzs', 'csv'), ('bcr-stats', 'csv'))
def export_bcr_map(ekey, dstore):
    oq = dstore['oqparam']
    assetcol = dstore['assetcol/array'].value
    aref = dstore['asset_refs'].value
    bcr_data = dstore[ekey[0]]
    N, R = bcr_data.shape
    if ekey[0].endswith('stats'):
        tags = ['mean'] + ['quantile-%s' % q for q in oq.quantile_loss_curves]
    else:
        tags = ['rlz-%03d' % r for r in range(R)]
    loss_types = dstore.get_attr('composite_risk_model', 'loss_types')
    fnames = []
    writer = writers.CsvWriter(fmt=writers.FIVEDIGITS)
    for t, tag in enumerate(tags):
        for l, loss_type in enumerate(loss_types):
            rlz_data = bcr_data[loss_type][:, t]
            path = dstore.build_fname('bcr-%s' % loss_type, tag, 'csv')
            data = [['lon', 'lat', 'asset_ref', 'average_annual_loss_original',
                     'average_annual_loss_retrofitted', 'bcr']]
            for ass, value in zip(assetcol, rlz_data):
                data.append((ass['lon'], ass['lat'],
                             decode(aref[ass['idx']]),
                             value['annual_loss_orig'],
                             value['annual_loss_retro'],
                             value['bcr']))
            writer.save(data, path)
            fnames.append(path)
    return writer.getsaved()


@reader
def get_loss_ratios(lrgetter, monitor):
    with lrgetter.dstore:
        loss_ratios = lrgetter.get_all()  # list of arrays of dtype lrs_dt
    return list(zip(lrgetter.aids, loss_ratios))


@export.add(('asset_loss_table', 'hdf5'))
@depr('This exporter will be removed soon')
def export_asset_loss_table(ekey, dstore):
    """
    Export in parallel the asset loss table from the datastore.

    NB1: for large calculation this may run out of memory
    NB2: due to an heisenbug in the parallel reading of .hdf5 files this works
    reliably only if the datastore has been created by a different process

    The recommendation is: *do not use this exporter*: rather, study its source
    code and write what you need. Every postprocessing is different.
    """
    key, fmt = ekey
    oq = dstore['oqparam']
    assetcol = dstore['assetcol']
    arefs = dstore['asset_refs'].value
    avals = assetcol.values()
    loss_types = dstore.get_attr('all_loss_ratios', 'loss_types').split()
    dtlist = [(lt, F32) for lt in loss_types]
    if oq.insured_losses:
        for lt in loss_types:
            dtlist.append((lt + '_ins', F32))
    lrs_dt = numpy.dtype([('rlzi', U16), ('losses', dtlist)])
    fname = dstore.export_path('%s.%s' % ekey)
    monitor = performance.Monitor(key, fname)
    aids = range(len(assetcol))
    allargs = [(riskinput.LossRatiosGetter(dstore, block), monitor)
               for block in split_in_blocks(aids, oq.concurrent_tasks)]
    dstore.close()  # avoid OSError: Can't read data (Wrong b-tree signature)
    L = len(loss_types)
    with hdf5.File(fname, 'w') as f:
        nbytes = 0
        total = numpy.zeros(len(dtlist), F32)
        for pairs in parallel.Starmap(get_loss_ratios, allargs):
            for aid, data in pairs:
                asset = assetcol[aid]
                avalue = avals[aid]
                for l, lt in enumerate(loss_types):
                    aval = avalue[lt]
                    for i in range(oq.insured_losses + 1):
                        data['ratios'][:, l + L * i] *= aval
                aref = arefs[asset.idx]
                f[b'asset_loss_table/' + aref] = data.view(lrs_dt)
                total += data['ratios'].sum(axis=0)
                nbytes += data.nbytes
        f['asset_loss_table'].attrs['loss_types'] = ' '.join(loss_types)
        f['asset_loss_table'].attrs['total'] = total
        f['asset_loss_table'].attrs['nbytes'] = nbytes
    return [fname]
