"""
Wrapper around the spline detrending.
"""
from argparse import ArgumentParser
from glob import glob
import os

from astropy.io import fits
import h5py
import pandas as pd
import matplotlib
matplotlib.use('Agg')
from matplotlib.pylab import *

import photometry
import h5plus
import prepro
import cotrend
import k2_catalogs
import cPickle as pickle

parser = ArgumentParser(description='Ensemble calibration')
parser.add_argument('fitsdir',type=str,help='directory with fits files')
parser.add_argument('-f',action='store_true',
                     help='Force re-creation of h5 checkpoint file')
parser.add_argument('--algo',type=str,help='[PCA|ICA]',default='PCA')
args = parser.parse_args()

# Loading up all the fits files takes some time. The first order of
# business is to create a checkpoint.
dir = args.fitsdir
algo = args.algo

dirname = os.path.dirname(dir)
h5file = "%s.h5" % (dirname)
if not os.path.exists(h5file) or args.f:
    fL = glob('%s/*.fits' % dirname)
    nfL = len(fL)
    print "loading up %i files" % nfL

    lcL = []
    epicL = []

    for i in range(nfL):
        f = fL[i]
        lc = photometry.read_crossfield_fits(fL[i])
        lc = prepro.rdt(lc)
        epic = os.path.basename(f).replace('.fits','')
        if i%100==0:
            print i

        lcL+=[lc]
        epicL+=[epic]

    lc = np.vstack(lcL)
    epic = np.array(epicL)
    
    print "Creating h5 checkpoint: %s" % h5file
    with h5plus.File(h5file) as h5:
        h5['lc'] = lc
        h5['epic'] = epic

# Load up files from h5 database
print "Reading files from %s" % h5file
with h5py.File(h5file) as h5:
    lc = h5['lc'][:]
    epic = h5['epic'][:]

fdt = ma.masked_array(lc['fdt'],lc['fmask'])
epic = np.array(pd.Series(epic).str.replace('.pickle','').astype(int))
#epic = epic.astype(int)
dftr = pd.DataFrame(dict(i=arange(len(epic))),index=epic)
dftr['epic'] = dftr.index
targets = k2_catalogs.read_cat(return_targets=True)
dftr = pd.merge(dftr,targets.drop_duplicates())

fdt = fdt[dftr.i]
ec = cotrend.EnsembleCalibrator()
ec.add_training_set(fdt,dftr)
ec.robust_components(algo=algo)

ec.plot_basename = ec.plot_basename.replace('cotrend',dirname)
cotrend.makeplots(ec,savefig=True)

h5file = dirname+'_ec.h5'
print "Saving calibrator object to %s" % h5file
cotrend.to_hdf(ec,h5file)

