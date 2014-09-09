"""
Routines & functions for analysis of K2 ("Kepler2") data.

To implement the "Vanderburg algorithm" of Vanderburg & Johnson (2014;
http://adsabs.harvard.edu/cgi-bin/bib_query?arXiv:1408.3853), see the
main driver function :func:`runPixelDecorrelation` (for fixed aperture
size) the super-driver function :func:`runOptimizedPixelDecorrelation`
(to optimize the aperture size), or see the command-line example
below.


:EXAMPLES:
    To avoid hassles, now runs directly from the command line. To see a
    list of all command-line options, just enter:
     ::

      python k2.py --help

    Assuming the desired data file is in your current working
      directory, an analysis of a K2 Engineering data field could be
      run using 3 CPU cores via: the command-line as follows:
     ::

      python k2.py -f kplr060017806-2014044044430_lpd-targ.fits -x 25 -y 25 -n 3 -r 4 --tmin=1862.45 --minrad=3 --maxrad=10 --verbose=1

    To run the same analysis, but use PRF-shaped photometric apertures
      (instead of circular apertures, as above) and avoid
      Gaussian-fitting-centroiding, 
     ::

      python k2.py -f kplr060017806-2014044044430_lpd-targ.fits -x 25 -y 25 --tmin=1862.45 --verbose=1 --apmode=prf --gausscen=0

    For a quick run on a Cycle 0 target: 
     ::

       python k2.py -f ktwo202136997-c00_lpd-targ.fits -x 13 -y 13 -n 12 -r 4 --tmin=1862.45 --minrad=2 --maxrad=8 --verbose=1 --gausscen=0 --plotmode=gs

:REQUIREMENTS:
  Has only been tested on Linux & OS X. 

  Public Python modules:
    matplotlib / pylab (tested with v1.1.0, 1.3.1)

    NumPy (tested with v1.6.2, 1.8.1)

    SciPy (tested with 0.7.0, 0.10.1, 0.14.0)

    AstroPy (for io.fits; tested with v0.4, 0.4.1) or PyFITS (v3.1.1; deprecated)

    Tested with Python v2.7.3, 2.7.6, 2.7.8

  Private Python modules:
    analysis.py -- http://www.lpl.arizona.edu/~ianc/python/analysis.html

    tools.py -- http://www.lpl.arizona.edu/~ianc/python/tools.html

    phot.py -- http://www.lpl.arizona.edu/~ianc/python/phot.html

:HISTORY:
  2014-08-27 16:17 IJMC: Created.

  2014-09-02 18:48 IJMC: Spruced up and sent to E.P.: v0.1.0

  2014-09-04 14:45 IJMC: Implemented PRF-based aperture generation
                         with '--apmode'/apertureMode. Starting
                         PRF-fitting code. Renamed
                         :func:`extractPhotometryFromPixelData` to
                         :func:`aperturePhotometryFromPixelData`.

  2014-09-08 16:54 IJMC: Updated to work with K2 Cycle 0 data.      
  2014-09-08 EAP: Added in WCS option
  2014-09-08 EAP: Minor fixes to xcorr algorithm
"""

# Import standard Python modules:
import matplotlib
matplotlib.use('Agg')  # Should allow plotting directly to files.

import numpy as np
from numpy import ma

import pylab as py
from scipy import interpolate
from scipy import signal
from multiprocessing import Pool
from optparse import OptionParser
import os
import sys
import warnings
from scipy import ndimage as nd
import pandas as pd
import photometry

warnings.simplefilter('ignore', np.RankWarning) # For np.polyfit
try:  
    from astropy.io import fits as pyfits
except:
    import pyfits

# Import my personal modules:
import analysis as an
import tools
import phot
try:
    import _chi2  # Leverage my c-based chi-squared routine:
    c_chisq = True
except:
    c_chisq = False

__version__ = '0.3.0'

_prfpath = os.path.expanduser('~/proj/transit/kepler/prf/')


# Begin definitions!
def prfpath():
    return _prfpath

class baseObject:
    """Empty object container.
    """
    # 2010-01-24 15:13 IJC: Added to spitzer.py (from my ir.py)
    def __init__(self):
        return

    def __class__(self):
        return 'baseObject'

def main(argv=None):
    if argv is None:
        argv = sys.argv

    narg = len(argv)
    #_save = os.path.expanduser('~') + '/proj/transit/kepler/proc/'
    #_data = os.path.expanduser('~') + '/proj/transit/kepler/data/'

    _save = os.getcwd() + '/'
    _data = os.getcwd() + '/'

    if narg==1:  # E.g., running from within Python interpreter:
        # Use these 3 parameters for 'original' Kepler data:
        fn = _data + 'kplr009390653-2010265121752_lpd-targ.fits'
        tlimits = None
        xcen, ycen = 1,3

        # Use these 3 parameters for "K2" Kepler data:
        fn = _data + 'kplr060018007-2014044044430_lpd-targ.fits'
        tlimits = [1862.45, np.inf]
        xcen, ycen = 25, 25

        nthreads = 1
        resamp = 1  # photometry oversampling factor
        nordGeneralTrend = 5
        fs = 15
        minrad, maxrad = 1.5, 15
        gausscen = 0

        output = 1
        plotmode = 'texexec' 

    else:  # Probably running from the command line.
        p = OptionParser()

        p.add_option('-f', '--file', dest='fn', type='string', metavar='FILE',
                     help='Pixel data filename', action='store')
        p.add_option('-x', '--xcen', dest='xcen', type='float', 
                     help='Row (X-coordinate) of target in frame')
        p.add_option('-y', '--ycen', dest='ycen', type='float', 
                     help='Column (Y-coordinate) of target in frame')
        p.add_option('--aper',dest='aper', type='int', 
                     help='Determine Star Position From Kepler Aperture'
                     ,default=False)
        p.add_option('--wcs',dest='wcs', type='int', 
                     help='Determine Star Position WCS'
                     ,default=False)
        p.add_option('-n', '--nthreads', dest='nthreads', type='int', 
                     help='Number of threads for multiprocessing.', default=1)
        p.add_option('-r', '--resamp', dest='resamp', type='int', 
                     help='Resampling factor for partial-pixel photometry.', 
                     default=1)
        p.add_option('-g', '--gentrend', dest='nordGeneralTrend', type='int', 
                     help='Polynomial order for fitting general trend.', 
                     default=5)
        p.add_option('--apmode', dest='apertureMode', type='str', 
                     help='Aperture mode: "circular" (default) or "prf"', 
                     default='circular')
        p.add_option('--minrad', dest='minrad', type='float', 
                     help='Minimum aperture radius (pixels)', default=1.5)
        p.add_option('--maxrad', dest='maxrad', type='float', 
                     help='Maximum aperture radius (pixels)', default=15)
        p.add_option('--tmin', dest='tmin', type='float', 
                     help='Minimum valid time index. (e.g., 1862.45 for K2 engineering)', default=1862.45)
        p.add_option('--tmax', dest='tmax', type='float', 
                     help='Maximum valid time index.', default=np.inf)
        p.add_option('--gausscen', dest='gausscen', type='int', 
                     help='Fit 2D gaussians for centroids if 1 (DEFAULT) or not (if 0)', default=1)
        p.add_option('--fs', '--fontsize', dest='fs', type='float', 
                     help='Font size for plots.', default=15)
        p.add_option('-d', '--datadir', dest='_data', type='string', 
                     metavar='DIR', help='Load data from this directory.', 
                     action='store', default=_data)
        p.add_option('-s', '--savedir', dest='_save', type='string', 
                     metavar='DIR', help='Save data into this directory.', 
                     action='store', default=_save)
        p.add_option('--plotalot', dest='plotalot', type='int', 
                     help='Set verbose generation of plots.', action='store', 
                     default=False)
        p.add_option('--verbose', dest='verbose', type='int', 
                     help='Set verbosity level for output text.', 
                     action='store', default=0)
        p.add_option('--output', dest='output', type='int', 
                     help='0=pickled dict (DEFAULT), 1=pickled object (less compatible), 2=FITS (limited data)', 
                     action='store', default=0)
        p.add_option('--plotmode', dest='plotmode', type='string', 
                     help="'texexec' or 'gs' are best, but 'tar' is safest.", 
                     action='store', default='tar')

        options, args = p.parse_args()

        print ""
        print "Running motion decorrelation on %s" % options.fn
        print ""

        fn       = options.fn

        if options.aper:
            xcen,ycen = photometry.get_star_pos(fn,mode='aper')
            pos_mode = 'aper'
        elif options.wcs:
            xcen,ycen = photometry.get_star_pos(fn,mode='wcs')
            pos_mode = 'wcs'
        else:
            xcen     = options.xcen
            ycen     = options.ycen
            pos_mode = 'manual'

        print "Using position mode %s, star is at pixels = [%.2f,%.2f]" % \
            (pos_mode,xcen,ycen)

        nthreads = options.nthreads
        resamp   = options.resamp
        nordGeneralTrend = options.nordGeneralTrend
        apertureMode   = options.apertureMode
        minrad   = options.minrad
        maxrad   = options.maxrad
        tmin     = options.tmin
        tmax     = options.tmax
        fs       = options.fs
        _save    = options._save
        _data    = options._data
        plotalot = options.plotalot
        verbose  = options.verbose 
        gausscen = options.gausscen
        output   = options.output
        plotmode = options.plotmode

        tlimits = [tmin, tmax]

        if not os.path.isfile(fn):
            fn = _data + fn

    # Setup Pool for multiprocessing support:
    if nthreads==1:
        pool = None
    else:
        pool = Pool(processes=nthreads)

    # Run the code:
    results = runOptimizedPixelDecorrelation(
        fn, (xcen, ycen), apertureMode=apertureMode, resamp=resamp, 
        nordGeneralTrend=nordGeneralTrend, pool=pool, tlimits=tlimits, 
        verbose=verbose, plotalot=0, minrad=minrad, maxrad=maxrad, 
        gausscen=gausscen)
 
#    EAP future work, define aperatures beforehand.
#    results = runPixelDecorrelation(
#        fn, loc, rap, apertureMode=apertureMode, resamp=resamp, 
#        nordGeneralTrend=nordGeneralTrend, verbose=verbose, 
#        plotalot=plotalot, xy=xy, prfFrac=thisFrac, tlimits=tlimits, 
#        gausscen=gausscen, nthreads=nthreads, pool=pool)
#

    results.argv = argv
    savefile = '%s%09d' % (_save, results.headers[0]['KEPLERID'])

    # Save everything to disk:
    if output==0 or output==1: # Save a pickle:
        picklefn = savefile + '.pickle'
        if output==0: # Save a simple dict:
            tools.savepickle(tools.obj2dict(results), picklefn)
        elif output==1: # Save the object itself:
            tools.savepickle(results, picklefn)

    elif output==2: #Save a FITS file
        hdu1 = results2FITS(results)
        fitsfn = savefile + '.fits'
        hdu1.writeto(fitsfn,clobber=True)

    # Plot pretty pictures & print to disk:
    plotPixelDecorResults(results, fs=fs)
    pdffn = savefile + '.pdf'

    tools.printfigs(pdffn, pdfmode=plotmode, verbose=verbose)
    py.close('all')
    return

def results2FITS(o):
    """Convert results from :func:`runOptimizedPixelDecorrelation` or
    :func:`runPixelDecorrelation` into a FITS Header unit suitable for
    writing to disk."""
    # 2014-09-02 18:44 IJMC: Created
    
    names = 'time cad rawFlux cleanFlux decorMotion decorBaseline bg x y arcLength noThrusterFiring'.split() 
    data = [getattr(o,n) for n in names]

    # Unfortunately, there is some weird bug with how astropy stores
    # booleans in tables, so I'll convert the noThrusterFiring to ints
    data = np.rec.fromarrays(data,names=names)
    data = pd.DataFrame(data)
    data['noThrusterFiring'] = data['noThrusterFiring'].astype(int)
    data = np.array(data.to_records(index=False))
    hdu = pyfits.BinTableHDU(data=data)

    hdu.header['time'] = 'Time, BJD_TDB'
    hdu.header['rawFlux'] = 'Raw aperture photometry'
    hdu.header['cleanFlux'] = 'Cleaned, detrended photometry'
    hdu.header['decorMotion'] = 'Motion component of decorrelation.'
    hdu.header['decorBaseline'] = 'Long-term trend component of decorrelation.'
    hdu.header['bg'] = 'Background from photometry.'
    hdu.header['x'] = 'X motion (pixels).'
    hdu.header['y'] = 'Y motion (pixels).'
    hdu.header['arcLength'] = 'Length along arc (pixels).'
    hdu.header['noThrusterFiring'] = 'No Thruster Firing Identified'
    hdu.header['APRAD0'] = o.apertures[0]
    hdu.header['APRAD1'] = o.apertures[1]
    hdu.header['APRAD2'] = o.apertures[2]
    hdu.header['LOC1'] = o.loc[0]
    hdu.header['LOC2'] = o.loc[1]
    for key in ('kepmag', 'kid', 'resamp', 'rmsCleaned', 'rmsHonest', 'nordArc', 'nordPixel1d', 'nordGeneralTrend', 'rmsCleaned', 'rmsHonest'):
        val = getattr(o, key)
        if hasattr(val, '__iter__'):
            hdu.header[key] = val[0]
        else:
            hdu.header[key] = val

    return hdu

def runOptimizedPixelDecorrelation(fn, loc, apertures=None, apertureMode='circular', resamp=1, nordGeneralTrend=-1.5, verbose=False, plotalot=False, xy=None, tlimits=[1862.45, np.inf], nthreads=1, pool=None, minrad=2, maxrad=15, minSkyRadius=4, skyBuffer=2, skyWidth=3, niter=12, gausscen=True):

    """Run (1D) pixel-decorrelation of Kepler Data, and optimized
    aperture too. If you want a single, fixed aperture then use
    :func:`runPixelDecorrelation` instead.

    :INPUTS:
      The same as for :func:`runPixelDecorrelation`, with a few additions:

      minrad : positive scalar
        The smallest valid aperture radius, in pixels.

      maxrad : positive scalar
        The largest valid aperture radius, in pixels. For very faint
        targets, this should probably be set smaller than ~8.

      minSkyRadius : positive scalar
        Minimum radius of the inner sky annulus aperture, in pixels.

      minSkyBuffer : positive scalar
        Minimum buffer, in pixels, between the target aperture and the
        inner sky annulus aperture.

      skyBuffer : positive scalar
        Radius difference between inner sky annulus aperture and
        target aperture.

      skyWidth : positive scalar
        The width of the sky annulus aperture.

      gausscen : bool
        If True, fit 2D Gaussians to the PSFs as an additional
        centroiding mechanism.  This is unfortunately rather slow!

    :NOTES:
      This routine tried to optimize the photometric extraction
      aperture based on the RMS in the final light curve. Thus, it is
      poorly-suited to targets with rapid, high intrinsic variability.
    """
    # 2014-08-29 11:59 IJMC: Created
    # 2014-09-06 17:53 IJMC: Added 'apertureMode' option.
    
    # Parse inputs:
    apertureMode = apertureMode.lower()
    if apertureMode[0:4]=='circ':
        inTol = 0.1
        inner_ap_radii = np.arange(minrad, min(6, maxrad))
        if maxrad>6:
            nlog = np.int(np.log(maxrad/6.) / np.log(1.2))
            inner_ap_radii = np.concatenate((inner_ap_radii, 6*1.2**np.arange(nlog+1)))
            inner_ap_radii = inner_ap_radii[inner_ap_radii <= maxrad]
        if inner_ap_radii.size < 3:
            inner_ap_radii = np.linspace(minrad, maxrad, 3)
        prfFrac = [None ] * len(inner_ap_radii)

    elif apertureMode=='prf':
        defaultR0 = minrad
        prfFrac = [0.8, 0.9, 0.933, 0.966, 0.999, 0.9999]
        inTol = 0.01
        inner_ap_radii = [defaultR0] * len(prfFrac)
    else:
        print "Aperture mode '%s' unknown. Exiting!" % apertureMode
        return -1
        
    # Define a whole slew of helper function:
    def getAperRadii(targRad):
        if np.array(targRad).ndim>0:  targRad = targRad[0]
        targRad = max(min(targRad, maxrad), minrad)
        skyInner = max(targRad + skyBuffer, minSkyRadius)
        skyOuter = skyInner + skyWidth
        return tuple(np.array([targRad, skyInner, skyOuter]).squeeze())

    def getAperParam(targRad, frac=None):
        if np.array(targRad).ndim>0:  targRad = targRad[0]
        targRad = max(min(targRad, maxrad), minrad)
        skyInner = max(targRad + skyBuffer, minSkyRadius)
        skyOuter = skyInner + skyWidth
        if frac is None:
            thisFrac = None
        else:
            if frac<0.4:
                thisFrac = 0.4
            elif frac>1:
                thisFrac = 1.0
            else:
                thisFrac = frac
        return tuple(np.array([targRad, skyInner, skyOuter]).squeeze()), np.array([thisFrac]).min()

    def nearlyIn(val1, seq, tol=inTol):
        seq = np.array(seq, copy=False)
        return (np.abs(seq - val1)<=tol).any()
            
    def genNextGuess(rmses, apertureMode):
        if apertureMode[0:4]=='circ':
            params = inner_ap_radii
        elif apertureMode=='prf':
            params = prfFrac
        best1 = (np.array(rmses)==rmses.min()).nonzero()[0][0]
        best2 = np.array(rmses)<=np.sort(rmses)[1]
        best3 = np.array(rmses)<=np.sort(rmses)[2]
        RMSfit = np.polyfit(np.array(params)[best3], rmses[best3], 2)
        nextguess = -0.5*RMSfit[1]/RMSfit[0]
        if apertureMode[0:4]=='circ':
            inLimits = nextguess>=minrad and nextguess<=maxrad
        else:
            inLimits = nextguess > 0.4 and nextguess <= 1.0

        if RMSfit[0]<0 or nextguess in params or not inLimits:
            linfit = np.polyfit(np.array(params)[best2], rmses[best2], 1)
            nextguess = params[best1] - np.sign(linfit[0]) * max(minstep, np.abs(np.diff(np.array(params)[best2][0:2])))
        #pdb.set_trace()

        if apertureMode[0:4]=='circ':
            nextrad, nextfrac = nextguess, None
        elif apertureMode=='prf':
            nextrad, nextfrac = inner_ap_radii[0], nextguess

        return getAperParam(nextrad, nextfrac)

    if verbose: 
        print "Starting K2 aperture-photometry optimization run."
        print " Filename is: " + fn

        
    # Finally, we're ready: begin!
    outputs = []
    for rap0, frac in zip(inner_ap_radii, prfFrac):
        rap, thisFrac = getAperParam(rap0, frac)
        outputs.append(runPixelDecorrelation(fn, loc, rap, apertureMode=apertureMode, resamp=resamp, nordGeneralTrend=nordGeneralTrend, verbose=verbose, plotalot=plotalot, xy=xy, prfFrac=thisFrac, tlimits=tlimits, gausscen=gausscen, nthreads=nthreads, pool=pool))

    if verbose:
        print "Finished with initial grid of aperture sizes. Now home in."


    # Do a really crude homing-in algorithm. It's tough since the
    # underlying function is unlikely to be smooth -- there's still
    # room for improvement here:
    manyRMS = np.array([o.rmsHonest for o in outputs]).squeeze()
    minstep = 0.1
    thisstep = 1.
    for jj in range(niter):
        nextrap, nextFrac = genNextGuess(manyRMS, apertureMode)

        #print rap[0], np.sort(inner_ap_radii)
        thisIter = 0
        if apertureMode[0:4]=='circ':
            alreadyTriedThisGuess = nearlyIn(nextrap[0], inner_ap_radii, tol=0.1)
        elif apertureMode=='prf':
            alreadyTriedThisGuess = nearlyIn(nextFrac, prfFrac, tol=0.01)

        while alreadyTriedThisGuess and thisIter<100:
            best1 = (manyRMS==manyRMS.min()).nonzero()[0][0]
            if apertureMode[0:4]=='circ':
                nextrad = min(max(inner_ap_radii[best1] + thisstep*np.random.randn(), minrad), maxrad)
                nextFrac = None
            elif apertureMode=='prf':
                nextrad = inner_ap_radii[0]
                nextFrac = min(max(prfFrac[best1] + thisstep * np.random.randn(), 0.4), 1.0)
            thisstep = max(minstep, thisstep*0.5)
            nextrap, nextFrac = getAperParam(nextrad, nextFrac)
            thisIter +=1
            if verbose>1:   print "Last guess basically already tried. Retrying." % rap[0]
            if thisIter==100:  thisStep = 0.5
            if apertureMode[0:4]=='circ':
                alreadyTriedThisGuess = nearlyIn(nextrap[0], inner_ap_radii, tol=0.1)
            elif apertureMode=='prf':
                alreadyTriedThisGuess = nearlyIn(nextFrac, prfFrac, tol=0.01)

        outputs.append(runPixelDecorrelation(fn, loc, nextrap, apertureMode=apertureMode, resamp=resamp, nordGeneralTrend=nordGeneralTrend, verbose=verbose, plotalot=plotalot, xy=xy, tlimits=tlimits, gausscen=gausscen, prfFrac=nextFrac, nthreads=nthreads, pool=pool))
        inner_ap_radii = np.concatenate((inner_ap_radii, [nextrap[0]]))
        prfFrac = np.concatenate((prfFrac, [outputs[-1].prfFrac]))
        manyRMS = np.array([o.rmsHonest for o in outputs]).squeeze()

        if verbose:
            if apertureMode[0:4]=='circ':
                print "Finished with iteration %i/%i. Last guess ap. radius: %1.2f" % (jj+1, niter, inner_ap_radii[-1])
            elif apertureMode=='prf':
                print "Finished with iteration %i/%i. Last guess PRF fraction: %1.4f" % (jj+1, niter, prfFrac[-1])
            
    manyRMS = np.array([o.rmsHonest for o in outputs]).squeeze()
    cleanRMS = np.array([o.rmsCleaned for o in outputs]).squeeze()

    finalIndex = (manyRMS==manyRMS.min()).nonzero()[0][0]
    finalOutput = outputs[finalIndex]
    finalOutput.search_inner_ap_radii = inner_ap_radii
    finalOutput.search_prfFrac = prfFrac
    finalOutput.search_rms = manyRMS
    finalOutput.search_rms_aggressive = cleanRMS

    return finalOutput

def runPixelDecorrelation(fn, loc, apertures, apertureMode='circular', resamp=1, nordGeneralTrend=-1.5, verbose=False, plotalot=False, xy=None, prfFrac=None, tlimits=[1862.45, np.inf], nthreads=1, pool=None, gausscen=True):
    """Run (1D) pixel-decorrelation of Kepler Data with a single aperture setting.

    :INPUTS:
      fn : str
        Filename of pixel file to load.

      loc: 2-sequence
        indexing coordinates of target. Need not be integers, but if
        converted to int these would index the approximate location of
        the target star.

        If loc is None, just use the brightest pixel. This is dangerous!

      apertures : various
        If a 3-sequence, this indicates the *radii* of three circular
        apertures (in pixels).  Passed to
        :func:`aperturePhotometryFromPixelData`

        If apertures are constructed using PRF flux-fractions
        (aperturemode='prf' and prfFrac not None), then the relative
        sense is still preserved: np.diff(apertures) is used to set
        the size of the buffer region and width of the sky annulus.

      aperturemode : str
        Either "circular" (default; for standard, circular-aperture
        photometry) or "prf". The latter option generates a model PRF
        and makes a mask that encloses 'prfFrac' of the total PRF
        flux. Input 'apertures' defines the sky aperture, as described above.

      resamp : int
        Factor by which to interpolate frame before measuring
        photometry (in essence, does partial-pixel aperture
        photometry). Ignored if 'aperturemode' is set to "prf".

      nordGeneralTrend : int
        Polynomial order to remove slow, overall trends from the photometry.

        if Negative, we instead median-bin the data in bins of width
        '-nordGeneralTrend' *days*, fit a linear spline, and divide
        out that as the trend instead. 

      xy : 2-sequence of 1D NumPy arrays
        If you think you *know* the relative motions of your stars on
        the detector, you can save considerable time by inputting them
        here. GIGO.

      prfFrac : None or scalar
        Fraction of model PRF flux to ecnlose when generating target
        aperture, if 'aperturemode' is set to "prf".

      tlimits : 2-sequence of scalars
        Valid range for timestamps.  To exclude K2 early-engineering
        data, set to [1862.45, np.inf].  Set to None for no limits.

      gausscen : bool
        If True, fit 2D Gaussians to the PSFs as an additional
        centroiding mechanism.  This is unfortunately rather slow!

      nthreads : positive integer
        Set >1 for multithreaded processing.  At present this is only
        used for fitting 2D Gaussians in
        :func:`getCentroidsGaussianFit` (which takes up the most time).

      pool : multiprocessing.Pool() object
        If you like, pass in a ready-made Pool() object. I find this
        gives me fewer problems than using 'nthreads'.
        


    :OUTPUTS:
      A container-type object with many relevant fields. A few of the
      most important are demonstrated in the example below.

    :TO-DO:
      Maybe add option for outputs in other formats (FITS, array,
      dict, etc.)?

    :EXAMPLE:
     ::
      
      import k2
      import pylab as py
      import os

      _data = os.path.expanduser('~/proj/transit/kepler/data/')
      fn = _data + 'kplr060021426-2014044044430_lpd-targ.fits'
      xcen, ycen = 25, 25
      ap_radii = [5, 7, 9]
      resamp = 1

      # Run the analysis:
      output = k2.runPixelDecorrelation(fn, (xcen, ycen), ap_radii, resamp=resamp, nordGeneralTrend=-1.5):

      # Plot the results:
      k2.plotPixelDecorResults(finalOutput, fs=15)
    """
    # 2014-08-28 10:20 IJMC: Created
    # 2014-09-06 15:09 IJMC: Added aperturemode and prfFrac options.

    apertureMode = apertureMode.lower()
    if verbose: 
        print "Starting K2 aperture-photometry run."
        print " Filename is:   " + fn
        print " Apertures are: " + str(apertures)
        print " PRF fraction is: " + str(prfFrac)
        print " verbosity level is: %i" % verbose

    # Load data:
    cube,headers = loadPixelFile(fn, header=True, tlimits=tlimits)
    time, data, edata = cube['time'],cube['flux'],cube['flux_err']

    # Perform flat fielding
    data = ma.masked_invalid(data)
    data.fill_value=0
    fmed = ma.median(data.reshape(data.shape[0],-1),axis=1)
    data -= fmed[:,np.newaxis,np.newaxis]
    data = data.filled()


    # Extract photometry (add eventual hook for PRF fitting):
    flux, eflux, bg, testphot = aperturePhotometryFromPixelData(data, loc, apertures, resamp=resamp, verbose=verbose, retall=True)

    # Extract photometry:
    prfphot = False
    if prfphot: # PRF-fitting
        junkF, junkE, junkB, testphot = aperturePhotometryFromPixelData(data.mean(0), loc, apertures, resamp=resamp, verbose=verbose, retall=True)
        flux, bg, xPRF, yPRF, chiPRF = \
            fitPhotometryFromPixelData(fn, data, testphot.position, apertures, errstack=edata, verbose=verbose, nthreads=nthreads, pool=pool)

    else:        # Aperture photometry
        if apertureMode[0:4]=='circ':
            flux, eflux, bg, testphot = aperturePhotometryFromPixelData(data, loc, apertures, resamp=resamp, verbose=verbose, retall=True)
        elif apertureMode=='prf':
            medFrame = np.median(data, axis=0)
            loc = refineCentroid(medFrame, apertures, loc=loc, verbose=verbose)
            aperMask = generatePRFaperture(fn, np.median(data, axis=0), loc, apertures, prfFrac, eframe=edata.mean(0), kepmask=kepMask)
            while not aperMask.any():
                prfFrac += 0.1
                aperMask = generatePRFaperture(fn, np.median(data, axis=0), loc, apertures, prfFrac, eframe=edata.mean(0))
            flux, eflux, bg, testphot = aperturePhotometryFromPixelData(data, loc, aperMask, resamp=1, verbose=verbose, retall=True)
        else:
            print "Aperture mode '%s' unknown. Exiting!" % apertureMode
            return -1

    if xy is None:
        # Compute centroid motions in 3 different ways:
        minMove = 1e-3
        xys = []
        x0, y0 = xcorrStack(data, npix_corr=3)
        x0 = testphot.position[0] - x0
        y0 = testphot.position[1] - y0
        if x0.std()>minMove or y0.std()>minMove:
            xys.append((x0, y0))
        x1, y1 = getCentroidsStandard(data, mask=testphot.mask_targ, bg=bg)
        if x1.std()>minMove or y1.std()>minMove:
            xys.append((x1, y1))
        if gausscen:
            x2, y2 = getCentroidsGaussianFit(data, testphot.position, testphot.mask_targ, flux=np.median(flux), bg=np.median(bg), errstack=edata, plotalot=plotalot, nthreads=nthreads, pool=pool, verbose=verbose)
            if x2.std()>minMove or y2.std()>minMove:
                xys.append((x2, y2))
        if prfphot:
            xys.append((xPRF, yPRF))
            if xPRF.std()>minMove or yPRF.std()>minMove:
                xys.append((xPRF, yPRF))
    else:
        xys = [(xy[0], xy[1])]

    # Detrend the flux, picking optimal values for all parameters:
    out = detrendFluxArcMotion(time, flux, xys, nordGeneralTrend=nordGeneralTrend, these_nord_arcs=None, these_nord_pixel1d=None, goodvals=None, plotalot=plotalot, verbose=verbose)
    
    # Stick everything into a big container-object:
    output = baseObject()
    output.headers = headers
    output.kid = headers[0]['KEPLERID']
    output.kepmag = headers[0]['KEPMAG']
    output.apertures = apertures
    output.apertureMode = apertureMode
    output.prfFrac = prfFrac
    output.nordGeneralTrend = nordGeneralTrend
  
    output.nordArc = out.nord_arc
    output.nordPixel1d = out.nord_pixel1d
    output.arc_fit = out.arc_fit
    output.decorBaseline = out.baseline
    output.decorMotion = out.decor
    if False: output.detrendSpline = out.detrendSpline
    output.x = out.x
    output.y = out.y
    output.rmsCleaned = out.rmsCleaned
    output.rmsHonest = out.rmsHonest
    output.arcLength = out.s
    output.noThrusterFiring = out.noThrusterFiring.squeeze()
    output.goodvals = out.goodvals

    output.time = time
    output.rawFlux = flux
    output.resamp = resamp
    output.cleanFlux = flux / out.decor / out.baseline
    output.bg = bg
    output.loc = testphot.position
    output.cad = cube['CADENCENO']

    output.medianFrame = np.median(data, axis=0)
    output.crudeApertureMask = testphot.mask_targ

    return output


def loadPixelFile(fn, tlimits=None, bjd0=2454833, header=False):
    """
    Convert a Kepler Pixel-data file into time, flux, and error on flux.

    :INPUTS:
      fn : str
        Filename of pixel file to load.

      tlimits : 2-sequence
        Valid time interval (before application of 'bjd0'). 

      bjd0 : scalar
        Value that will be added to the time index. The default
        "Kepler Epoch" is 2454833.

      header : bool
        Whether to also return the FITS headers.

    :OUTPUTS:
      time, datastack, data_uncertainties, mask [, FITSheaders]
    """
    # 2014-08-27 16:23 IJMC: Created
    # 2014-09-08 09:59 IJMC: Updated for K2 C0 data: masks.
    # 2014-09-08 EAP: Pass around data with record arrays

    if tlimits is None:
        mintime, maxtime = -np.inf, np.inf
    else:
        mintime, maxtime = tlimits
        if mintime is None:
            mintime = -np.inf
        if maxtime is None:
            maxtime = np.inf

    f = pyfits.open(fn)
    cube = f[1].data

    # Because masks are not always rectangges, we have to deal with nans.
    flux0 = ma.masked_invalid(cube['flux'])
    flux0 = flux0.sum(2).sum(1)

    index = (cube['quality']==0) & np.isfinite(flux0) \
            & (cube['time'] > mintime) & (cube['time'] < maxtime) 

    cube = cube[index]
    cube['time'][:] = cube['time'] + bjd0

    if header:
        ret = (cube,) + ([tools.headerToDict(el.header) for el in f],)

    f.close()
    return ret

def aperturePhotometryFromPixelData(stack, loc, apertures, resamp=1, recentroid=True, verbose=False, retall=True):
    """
    :INPUTS:
      stack : 2D or 3D NumPy array.
        Stack of pixel data, e.g. from :func:`loadPixelFile`
      
      loc: 2-sequence
        indexing coordinates of target. Need not be integers, but if
        converted to int these would index the approximate location of
        the target star.
  
      apertures : various
        If a 3-sequence, this indicates the *radii* of three circular apertures.
  
        Otherwise, we'll have to think of something fancier to do.
  
    :NOTES:
      May have problems for data whose motions are comparable to or
      larger than the PSF size.
      """
    # 2014-08-27 16:25 IJMC: Created
    # 2014-09-04 15:32 IJMC: Moved 'refineCentroid' to separate function.

    if stack.ndim==2:
        stack = stack.reshape((1,)+stack.shape)

    nobs = stack.shape[0]
    frame0 = np.median(stack, axis=0)


    apertures = np.array(apertures)
    if len(apertures)==3:
        dap = np.array(apertures)*2
        mask = None
    elif apertures.shape==stack.shape or apertures.shape==frame0.shape:
        dap = None
        mask = apertures

    phot0 = phot.aperphot(frame0, pos=loc, dap=dap, mask=mask, resamp=1, 
                          retfull=True)
    if recentroid:
        loc = refineCentroid(frame0, apertures, loc=loc, mask=None, verbose=verbose)

    phot1 = phot.aperphot(frame0, pos=loc, dap=dap, mask=mask, resamp=1, retfull=True)
    phot4mask = phot.aperphot(frame0, pos=loc, dap=dap, mask=mask, resamp=resamp, retfull=True)
    if verbose>=2:
        py.figure()
        py.imshow(np.log10(np.abs(1.+phot1.mask_targ * (phot1.frame-phot1.bg))))
        py.colorbar()
        py.title('log10(frame)')

    if mask is None:
        mask = phot4mask.mask_targ + phot4mask.mask_sky*2.0

    phots = [phot.aperphot(frame, pos=loc, dap=dap, mask=mask, resamp=resamp, retfull=False) for frame in stack]

    flux = np.zeros(nobs, dtype=float)
    eflux = np.zeros(nobs, dtype=float)
    bg = np.zeros(nobs, dtype=float)
    for ii, o in enumerate(phots):
        flux[ii] = o.phot
        eflux[ii] = o.ephot
        bg[ii] = o.bg

    ret = flux, eflux, bg
    if retall:  ret = ret + (phot1,)
    return ret

def getCentroidsGaussianFit(stack, position, mask, flux=None, bg=None, widths=None, errstack=None, plotalot=False, nthreads=1, pool=None, verbose=False):
    """Measure centroids via 2D gaussian fitting.  Pretty slow!

    :INPUTS:
      stack : 2D or 3D NumPy array
        Stack of pixel data, e.g. from :func:`loadPixelFile`

      position : 2-sequence
        Coordinates at which the target of interest is located.

      mask : 2D or 3D NumPy array
        Boolean mask, False for all pixels that should be utterly ignored.

      flux : scalar or None
        Best guess for the total flux in the target.

      bg : scalar or None
        Best guess for the sky background at the target.

      widths : 2-sequence or None
        Best guess for the x- and y-widths of the Gaussian.

      errstack : 2D or 3D NumPy array, or None
        Uncertainties in the data found in 'stack'

      nthreads : positive integer
        Set >1 for multithreaded processing. See Notes, and 'pool'
        description below.

      pool : multiprocessing.Pool() object
        If you like, pass in a ready-made Pool() object. I find this
        gives me fewer problems than using 'nthreads'.

    :OUTPUTS:
      x, y

    :NOTES:
      When nthreads>1, one sometimes encounters strange errors like
      "malloc: *** error for object 0x10baf9000: pointer being freed
      already on death-row".  For me, this occurs on my MacBook Pro
      when I begin Python via "pylab" but not via "ipython" (v13.1,
      Python v2.7.6) or "python" (v2.7.6).  Any help in diagnosing
      this would be greatly appreciated!
    """
    # 2014-08-27 17:57 IJMC: Created

    userPool = False
    if pool is not None:
        nthreads = pool._processes
        userPool = True
    elif nthreads>1:
        #print "\nMultithreading does not work yet! Running with just one thread.\n"
        pool = Pool(processes=nthreads)


    if stack.ndim==2:
        stack = stack.reshape((1,)+stack.shape)
    if errstack is None:
        errstack = np.ones(stack.shape)
    elif errstack.ndim==2:
        errstack = errstack.reshape((1,)+errstack.shape)

    if mask.ndim==2:
        mask = np.tile(mask, (stack.shape[0], 1, 1))

    nobs = stack.shape[0]
    frame0 = np.median(stack, axis=0)
    eframe0 = np.median(errstack, axis=0)
    mask0 = mask.mean(0)

    if bg is None:
        bg = np.median(stack.ravel())
    if flux is None:
        flux = frame
    if widths is None:
        widths = 0.5, 0.5

    x1d, y1d = np.arange(stack.shape[2]), np.arange(stack.shape[1])
    yy, xx = np.meshgrid(x1d, y1d)

    guess = flux, widths[0], widths[1], position[0], position[1], np.pi, bg
    #gmodel = an.gaussian2d_ellip(guess, xx, yy)
    maxsize = max(frame0.shape)
    uniformprior = [(0, np.inf), (0, np.inf), (0, np.inf), (0, maxsize), (0, maxsize), None, None]
    fitkw = dict(uniformprior=uniformprior)
    fitargs = (an.gaussian2d_ellip, xx, yy, frame0, mask0/eframe0**2, fitkw)
    fit = an.fmin(errfunc, guess, args=fitargs, full_output=True, disp=verbose)
    if plotalot>=1:
        fmodel = an.gaussian2d_ellip(fit[0], xx, yy)
        py.figure()
        py.subplot(131)
        py.imshow(np.log10(np.abs(mask0*(frame0-bg)+1)))
        py.subplot(132)
        py.imshow(np.log10(np.abs(mask0*(fmodel-bg)+1)))
        py.subplot(133)
        py.imshow(np.log10(np.abs(mask0*(frame0-fmodel)+1)))



    if nthreads==1:
        if verbose: print "Begining single-threaded Gaussian fitting."
        gaussfits = np.zeros((nobs, fit[0].size), dtype=float)
        gausschis = np.zeros(nobs, dtype=float)
        for ii in xrange(nobs):
            fitargs = (an.gaussian2d_ellip, xx[mask[ii]], yy[mask[ii]], stack[ii][mask[ii]], 1./errstack[ii][mask[ii]]**2, fitkw)
            thisfit = an.fmin(errfunc, fit[0], args=fitargs, full_output=True, disp=False)
            gaussfits[ii] = thisfit[0]
            gausschis[ii] = thisfit[1]
            #mstack[ii] = an.gaussian2d_ellip(thisfit[0], xx, yy)


    else:
        if verbose: print "Begining multithreaded Gaussian fitting."
        test_kw = dict(full_output=True, disp=False)

        HUGEfitargs = [[errfunc, fit[0], (an.gaussian2d_ellip, xx[mask[jj]], yy[mask[jj]], stack[jj][mask[jj]], 1./errstack[jj][mask[jj]]**2, fitkw), test_kw] for jj in xrange(nobs)]
        test_fits = pool.map(an.fmin_helper2, HUGEfitargs)
        gaussfits = np.array([tt[0] for tt in test_fits])
        
        if not userPool:
            pool.close()
            pool.join()

    return gaussfits[:,3:5].T

def getCentroidsStandard(stack, mask=None, bg=None, strictlim=True):
    """Measure centroids via center-of-mass formulae.

    :INPUTS:
      stack : 2D or 3D NumPy array
        Stack of pixel data, e.g. from :func:`loadPixelFile`

      mask : 2D or 3D NumPy array
        Boolean mask, False for all pixels that should be utterly ignored.
        Useful for ignoring the effects of nearby, bright stars.

      bg : scalar or None
        Best guess for the sky background at the target in each
        frame. Useful for getting the centroiding just right.

      strictlim : bool
        If True, ensure that the resulting x,y values do not lie
        outside the dimensions of 'stack'

    :OUTPUTS:
      x, y
    """
    # 2014-08-27 18:17 IJMC: Created
    # 2014-09-08 10:50 IJMC: Updated for K2 C0; improved masking of nans.

    if stack.ndim==2:
        stack = stack.reshape((1,)+stack.shape)
    else:
        stack = stack.copy()

    nobs = stack.shape[0]
    if mask is None:
        mask = np.ones(stack.shape)
    #elif mask.ndim==2:
    #    mask = np.tile(mask, (nobs, 1, 1))

    if bg is None:
        bg = np.zeros(stack.shape[0])

    
    stack -= bg.reshape(nobs, 1, 1)

    x1d, y1d = np.arange(stack.shape[2]), np.arange(stack.shape[1])
    xx, yy = np.meshgrid(x1d, y1d)

    fsh = stack.shape
    sh12 = fsh[1]*fsh[2]
    #flux0.reshape(fsh[0], fsh[1]*fsh[2])[:, mask.ravel()].sum(1)
    denoms = stack.reshape(nobs, sh12)[:,mask.ravel()].sum(1)
    y2 = (stack * xx).reshape(nobs, sh12)[:,mask.ravel()].sum(1) / denoms
    x2 = (stack * yy).reshape(nobs, sh12)[:,mask.ravel()].sum(1) / denoms

    if strictlim:
        maxlim = max(stack.shape[1:])
        x2 = np.vstack((x2, np.zeros(nobs))).max(0)
        x2 = np.vstack((x2, maxlim*np.ones(nobs))).min(0)
        y2 = np.vstack((y2, np.zeros(nobs))).max(0)
        y2 = np.vstack((y2, maxlim*np.ones(nobs))).min(0)

    return x2, y2


def getArcLengths(time, xypairs, these_nord_arcs=None, verbose=False):
    """Measure the length along curved arcs, defined by x-y coordinates.
  
    :INPUTS:
      time : 1D NumPy array
        Time index at which X, Y values were measured.
  
      xypairs: sequence of 2-tuples 
        Sets of X & Y values, measured by various techniques.
  
      these_nord_arcs : sequence of positive ints
        Number of polynomial terms to use for fitting the rotated y'
        positions as a function of x'. Thus, zero is invalid. Each
        specified order will be tried. If None, defaults to
        np.arange(1,15)
    """
    # 2014-08-27 19:23 IJMC: Created

    if verbose: print "Measuring arc lengths for each set of (x,y)"

    nxy = len(xypairs)
    nobs = xypairs[0][0].size
    
    if these_nord_arcs is None:
        these_nord_arcs = np.arange(1, 15)

    nord = these_nord_arcs.size

    ss = np.zeros((nxy, nobs), dtype=float)
    nord_arcs = np.zeros(nxy, dtype=int)
    arc_fits = []
    thrusterFiringIndex = np.zeros((nxy, nobs), dtype=bool)
    for ii,xy in enumerate(xypairs):
        x, y = xy
        ### Rotate coordinate frames:
        rot,sjunk,vjunk = np.linalg.svd(np.cov(x, y))
        if rot[0,0]<0: rot *= -1
        xp, yp = np.dot(rot, np.vstack((x, y)))
        if xp.std()==0:
            xp_norm = np.ones(nobs, dtype=float)
        else:
            xp_norm = 2 * ((xp - xp.min()) / (xp.max() - xp.min()) - 0.5)


        ### Fit arc motions, iteratively rejecting outliers:
        arc_RMSes = np.zeros(nord)
        arc_npts = np.zeros(nord, int)
        these_arc_fits = []

        for jj in these_nord_arcs:
            xvecs = np.array([xp_norm**n for n in xrange(jj)]).T
            weights = np.ones(nobs)
            lastNgood = nobs+1
            while lastNgood > weights.sum():
                lastNgood = weights.sum()
                fit, efit = an.lsq(xvecs, yp, w=weights, checkvals=False)
                ypfit = np.dot(fit, xvecs.T)
                weights = np.abs(yp-ypfit) < (an.dumbconf(yp-ypfit, .683)[0]*5)
            arc_RMSes[jj-1] = (yp-ypfit)[weights].std()
            arc_npts[jj-1] = weights.sum()
            these_arc_fits.append(fit)
            #plot(xp, ypfit, '.')

        minRMS = arc_RMSes[np.isfinite(arc_RMSes)].min()
        arc_BICs = these_nord_arcs * np.log(arc_npts) + arc_npts * (arc_RMSes/minRMS)**2
        minBIC = arc_BICs[np.isfinite(arc_BICs)].min()
        nord_arcs[ii] = these_nord_arcs[arc_BICs==minBIC]
        fit = np.array(these_arc_fits)[arc_BICs==minBIC][0]
        arc_fits.append(fit)


        # Measure distance along arc:
        ss[ii] =  computePolyCurveDistance(xp_norm, fit) * (xp.max()-xp.min())/2.

        # Compute derivatives:
        dsdt = np.concatenate(([0], np.diff(ss[ii]) / np.diff(time)))
        # Mask outliers in derivative space ("thruster firings"):
        noFiring = np.ones(nobs, dtype=bool)
        for kk in xrange(10):
            noFiring = (np.abs(dsdt-np.median(dsdt)) < (an.dumbconf(dsdt[noFiring], .683)[0]*5))
        thrusterFiringIndex[ii] = True-noFiring


    return ss, thrusterFiringIndex, nord_arcs, arc_fits

def computePolyCurveDistance(x, coef, oversamp=100):
    """Compute distance along a polynomial curve, defined by input
    coordinates x and coefficients 'coef'.

    Specifically, we return:
      Integral_xmin^xi sqrt(1 + (df/dx)^2) dx
    for each point xi in x.
    """
    # 2014-08-26 10:29 IJMC: Created

    nobs = x.size
    nord = len(coef)

    x1fine = np.linspace(x.min(), x.max(), nobs*oversamp)
    dx = np.diff(x1fine).mean()
    xvecs1fine = np.vstack([x1fine**n for n in range(nord)]).T
    y1pfine = np.dot(coef, xvecs1fine.T)
    s1fine = np.concatenate(([0], np.cumsum(np.sqrt(1 + (np.diff(y1pfine)/dx)**2) * dx)))
    return np.interp(x, x1fine, s1fine)

#def estimatePhotometricTrend(time, flux, nord=5, goodvals=None, plotalot=False):
#    """
#    Documentation TBD -- 
#
#    """
#    # 2014-08-27 19:50 IJMC: Created
#
#    nobs = time.size
#    if goodvals is None:
#        goodvals = np.ones(nobs, dtype=bool)
#    else:
#        goodvals = np.array(goodvals, copy=True)
#
#    outliers = np.ones(nobs, bool)
#    while outliers[goodvals].any():
#        #spl = interpolate.UnivariateSpline(time[goodvals], flux[goodvals], w=1./eflux[goodvals]**2, k=5, s=nobs/4.)
#        pfit = np.polyfit(time[goodvals]-time.min(), flux[goodvals], nord)
#        baseline = np.polyval(pfit, time-time.min())
#        residuals = flux - baseline
#        outliers = np.abs(residuals) > (an.dumbconf(residuals[goodvals], .683)[0]*3)
#        goodvals[outliers] = False
#        if plotalot:
#            py.figure()
#            py.subplot(211)
#            py.plot(time, flux, '.k', time[goodvals], flux[goodvals], 'or', time, polyval(pfit, time-time.min()), '.c')
#            py.subplot(212)
#            py.plot(time, np.abs(residuals), '.k', time[goodvals], np.abs(residuals)[goodvals], 'or')
#            py.plot(xlim(), [(an.dumbconf(residuals[goodvals], .683)[0]*3)]*2, '--')
#
#    fluxDetrend = flux / baseline
#
#    return fluxDetrend, goodvals


def detrendFluxArcMotion(time, flux, xys, nordGeneralTrend=None, these_nord_arcs=None, these_nord_pixel1d=None, goodvals=None, plotalot=False, verbose=False):
    """
    See function name: remove effect of (projected 1D) motion on photometry.

    :INPUTS:
      time : 1D NumPy array
        Time index at which flux, X, Y values were measured.

      flux : 1D NumPy array
        Raw flux of the target at each timestep, e.g. from aperture photometry.

      xys: sequence of 2-tuples 
        Sets of X & Y values, measured by various techniques.

      nordGeneralTrend : int
        Polynomial order to remove slow, overall trends from the photometry.

        if Negative, we instead median-bin the data in bins of width
        '-nordGeneralTrend' *days*, fit a linear spline, and divide
        out that as the trend instead. 

      these_nord_arcs : sequence of positive ints
        Number of polynomial terms to use for fitting the rotated y'
        positions as a function of x'. Thus, zero is invalid. Each
        specified order will be tried. Passed to :func:`getArcLengths.

      these_nord_pixel1d : sequence of positive ints
        Number of polynomial terms to use for fitting the dependence
        of 'flux' on the projected arc motions from x and y. If None,
        defaults to range(3, 20)

      goodvals : 1D Numpy array (of type bool)
        True for usable mesurements; False elsewhere.
    """
    # 2014-08-27 20:06 IJMC: Created
    # 2014-09-08 14:48 IJMC: Added check in case xys is empty.


    # Compute the arc lengths:

    nxy = len(xys)
    nobs = time.size
    output = baseObject() 
    if nxy==0:
        output.x, output.y = np.zeros((2, nobs))
        output.s = np.zeros(nobs)
        output.decor = np.median(flux)
        output.rmsCleaned = flux.std() / output.decor
        output.rmsHonest = flux.std() / output.decor
        output.nord_arc = 0
        output.nord_pixel1d = 0
        output.arc_fit = np.array([1])
        output.baseline = np.ones(nobs)
        output.flux = flux
        output.goodvals = np.ones(nobs, dtype=bool)
        output.noThrusterFiring = np.ones(nobs, dtype=bool)
        return output

    ss, thrusterIndex, nord_arcs, arc_fits = getArcLengths(time, xys, these_nord_arcs, verbose=verbose)

    # Parse inputs:
    if these_nord_pixel1d is None:
        these_nord_pixel1d = np.arange(3, 20)
    if not isinstance(these_nord_pixel1d, np.ndarray):
        these_nord_pixel1d = np.array(these_nord_pixel1d)
    n1d = these_nord_pixel1d.size
    if goodvals is None:
        goodvals0 = True - thrusterIndex
    elif goodvals.ndim==1:
        goodvals0 = np.tile(goodvals, (nxy, 1))
    else:
        goodvals0 = goodvals

    goodvals = goodvals0.all(axis=0)

    # Fit detrended flux to (projected) stellar motion:
    baseline_decors = np.zeros((nxy, nobs), dtype=float)
    RMSes = np.zeros(nxy)
    detrendSplines = []
    allRMSes = np.zeros((nxy, n1d), dtype=float)
    honestRMSes = np.zeros((nxy, n1d), dtype=float)
    all_sff_decors = np.zeros((nxy, n1d, nobs), dtype=float)
    all_baseline_decors = np.zeros((nxy, n1d, nobs), dtype=float)
    t_norm = 2 * ((time - time.min()) / (time.max() - time.min()) - 0.5)
    if nordGeneralTrend>0:
        det = 'poly'
    else:
        det = 'bin'
        tbins = np.arange(time[goodvals].min(), time[goodvals].max(), -nordGeneralTrend)
        tnbins = 2 * ((tbins - time.min()) / (time.max() - time.min()) - 0.5)

    if verbose: print "Fitting combined (baseline*motion) decorrelation."
    for ii,this_s in enumerate(ss):
        if verbose>1: print "Starting iteration %i/%i." % (ii+1, len(ss))
        #nord_pixel1ds = np.zeros(n1d-1, dtype=int)
        these_splines = []
        #these_decors = np.zeros((nord_pixel1ds.size, nobs), dtype=float)
        for jj, nord in enumerate(these_nord_pixel1d):
            if verbose>1: print "Starting sub-iteration %i/%i." % (jj+1, len(these_nord_pixel1d))
            if False:   # Like Vanderburg & Johnson:
                fbins = np.linspace(this_s[goodvals].min(), this_s[goodvals].max(), nord)
                sbin,fbin,junk,efbin = tools.errxy(this_s[goodvals], fluxDetrend[goodvals], fbins, clean=dict(nsigma=3, remove='both', niter=1), yerr='std')
                finind = np.isfinite(sbin * fbin)
                these_splines.append(interpolate.UnivariateSpline(sbin[finind], fbin[finind], s=0, k=1))
                all_sff_decors[ii,jj] = these_splines[jj](this_s)
                fluxFinal = flux / all_sff_decors[ii,jj]
                if det=='poly':
                    pfit_decor = an.polyfitr(time[goodvals]-time.min(), (flux/all_sff_decors[ii,jj])[goodvals], nordGeneralTrend, 3)
                    all_baseline_decors[ii,jj] = np.polyval(pfit_decor, time-time.min())
                elif det=='bin':
                    tbin, fbin, junk, junk = tools.errxy(time[goodvals], (flux/all_sff_decors[ii,jj])[goodvals], tbins, xmode='mean', ymode='median')
                    all_baseline_decors[ii,jj] = np.interp(time-time.min(), tbin-time.min(), fbin)
            else:   # Seems more reliable:
                s_norm = 2 * ((this_s - this_s.min()) / (this_s.max() - this_s.min()) - 0.5)
                #svecs = np.array([this_s**n for n in range(nord)]).T
                #tvecs = np.array([t_norm**n for n in range(nordGeneralTrend)]).T

                newchi = 9e99
                dchi = 9e99
                #sz = svecs[goodvals].mean(0)
                seval = np.ones(nobs)
                iter = 0
                maxiter = 2000
                while np.abs(dchi)>0.1 and iter < maxiter:
                    #tfit, etfit = an.lsq(tvecs[goodvals], (flux / seval)[goodvals])
                    #teval = np.dot(tvecs, tfit)
                    #sfit, esfit = an.lsq(svecs[goodvals], (flux / teval)[goodvals])
                    #seval = np.dot(svecs, sfit)
                    if det=='poly':
                        tfit = np.polyfit(t_norm[goodvals], (flux / seval)[goodvals], nordGeneralTrend-1)
                        teval = np.polyval(tfit, t_norm)
                    elif det=='bin':
                        tbin, fbin, junk, junk = tools.errxy(t_norm[goodvals], (flux/seval)[goodvals], tnbins, xmode='mean', ymode='median')
                        good = np.isfinite(tbin) * np.isfinite(fbin)
                        teval = np.interp(t_norm, tbin[good], fbin[good])
                    if (teval==0).any():  tevel[teval==0] = 1.
                    sfit = np.polyfit(s_norm[goodvals], (flux / teval)[goodvals], nord-1)
                    seval = np.polyval(sfit, s_norm)
                    if (seval==0).any():  sevel[seval==0] = 1.
                    oldchi = newchi + 0.
                    newchi = ((flux - seval * teval)**2)[goodvals].sum()
                    dchi = oldchi - newchi
                    iter += 1
                    #print iter, newchi, oldchi

                if iter==maxiter and verbose>1:
                    print "Did not converge on a (baseline*motion) fit after %i iterations." % iter
                #allvecs = np.hstack((svecs, tvecs))
                #bigfit, ebigfit = an.lsq(allvecs, np.log(flux))

                #bigS = np.dot(svecs, bigfit[0:nord])
                #bigT = np.dot(tvecs, bigfit[nord:])
                all_baseline_decors[ii,jj] = teval
                all_sff_decors[ii,jj] = seval

            allRMSes[ii,jj] = (flux/all_sff_decors[ii,jj]/ all_baseline_decors[ii,jj])[goodvals].std()
            honestRMSes[ii,jj] = (flux/all_sff_decors[ii,jj]/ all_baseline_decors[ii,jj])[True - thrusterIndex[ii]].std()

            
            #abc = np.dot(allvecs, bigfit)

            if plotalot>=2:
                py.figure()
                py.plot(this_s[goodvals], fluxDetrend[goodvals], 'oc')
                py.plot(this_s, all_sff_decors[ii,jj], '.k', mfc='orange')
                py.errorbar(sbin, fbin, efbin, fmt='ok', ms=11)
                py.title('%i, %i' % (ii, jj))

        detrendSplines.append(these_splines)
        minRMS = allRMSes[np.isfinite(allRMSes)].min()
        allChisq = goodvals.sum() * (allRMSes/minRMS)**2
        allBIC = allChisq + np.log(goodvals.sum()) * these_nord_pixel1d

    # Select the model with the lowest final RMS:
    bestBIC = allBIC[np.isfinite(allBIC)].min()
    bestInd = (allBIC==bestBIC).nonzero()


    output.bestInd = bestInd
    output.x, output.y = xys[bestInd[0]]
    output.s = ss[bestInd[0]].squeeze()
    output.rmsCleaned = allRMSes[bestInd]
    output.rmsHonest = honestRMSes[bestInd]
    output.decor = all_sff_decors[bestInd].squeeze()
    output.nord_arc = nord_arcs[bestInd[0]]
    output.nord_pixel1d = (these_nord_pixel1d[bestInd[1]]-1)
    output.arc_fit = arc_fits[bestInd[0]]
    output.baseline = all_baseline_decors[bestInd].squeeze()
    if False: output.detrendSpline = detrendSplines[bestInd[0]][bestInd[1]]
    output.flux = flux
    output.goodvals = goodvals
    output.noThrusterFiring = True - thrusterIndex[bestInd[0]]

    if plotalot>=1:
        py.figure()
        py.plot(output.s, flux / output.baseline, 'or', mec='k')
        py.plot(output.s[goodvals], (flux / output.baseline)[goodvals], 'oc', mec='k')
        #plot(sbin, fbin, 'ok', ms=14)
        py.plot(output.s, output.decor, '.', color='orange')
        py.xlabel('Arclength [pixels]', fontsize=15)
        py.ylabel('Detrended Flux', fontsize=15)
        py.minorticks_on()


    return output

def plotPixelDecorResults(input, fs=15):
    """Plot the results of a pixel-decorrelation run.
    
    :INPUTS:
      input : object
        The resulting output from a successful call to
        :func:`runPixelDecorrelation`

      fs : positive scalar
        The font size.

    """
    # 2014-08-28 20:37 IJMC: Created

    titstr = 'EPIC %i, Kp=%1.2f' % (input.headers[0]['KEPLERID'], input.headers[0]['KEPMAG'])

    if hasattr(input, 'search_rms') and \
            (hasattr(input, 'search_inner_ap_radii') or hasattr(input, 'search_prfFrac')):
        if input.apertureMode[0:4]=='circ':
            xlab = 'Target Aperture Radius [pixels]'
            xdat = input.search_inner_ap_radii
            txtStr = 'Minimum: %1.1f ppm at R=%1.2f pixels' % (input.rmsHonest*1e6, input.apertures[0])
        elif input.apertureMode=='prf':
            xlab = 'Enclosed Fraction of Model PRF Energy'
            xdat = input.search_prfFrac
            txtStr = 'Minimum: %1.1f ppm at F=%1.4f' % (input.rmsHonest*1e6, input.prfFrac)

        ai = np.argsort(xdat)
        py.figure()
        ax1 = py.subplot(111, position=[.15, .15, .8, .75])
        py.semilogy(np.array(xdat)[ai], input.search_rms[ai]*1e6, 'oc-')
        py.xlabel(xlab, fontsize=fs)
        py.ylabel('RMS [ppm]', fontsize=fs)
        py.minorticks_on()
        #loglim = np.log10(np.array(py.ylim()))
        #abc = (np.logspace(*loglim, num=4*np.diff(loglim)+1))
        minmax = input.search_rms.min(), input.search_rms.max()
        factor = minmax[0] / minmax[1]
        yval = 1e6*(minmax[0] * np.sqrt(factor)), 1e6*(minmax[1] / np.sqrt(factor))
        py.ylim(yval)
        yticks = np.logspace(np.log10(yval[0]), np.log10(yval[1]), 8)
        py.yticks(yticks, ['%i' % el for el in yticks])
        ax = py.axis()
        py.plot([input.apertures[0]]*2, py.ylim(), '--k')
        py.axis(ax)
        py.title(titstr)
        py.text(.95, .9, txtStr, transform=ax1.transAxes, horizontalalignment='right', fontsize=fs)


    time = input.time
    if (time > 2454833).any():
        time -= 2454833
    fluxDetrend = input.rawFlux / input.decorBaseline

    py.figure(tools.nextfig(), [10, 6.5])
    ax1 = py.subplot(311, position=[.48, .65, .43, .2])
    py.plot(time, fluxDetrend, '.-k', mfc='c')
    py.ylabel('Normalized Flux', fontsize=fs)
    ax1.get_yaxis().set_major_formatter(py.FormatStrFormatter('%1.4f'))
    ax2 = py.subplot(312, position=[.48, .4, .43, .2])
    py.plot(time, input.x, '.-k', mfc='r')
    py.ylabel('X motion [pix]', fontsize=fs)
    ax3 = py.subplot(313, position=[.48, .15, .43, .2])
    py.plot(time, input.y, '.-k', mfc='r')
    py.ylabel('Y motion [pix]', fontsize=fs)
    py.xlabel('BJD - 2454833', fontsize=fs)

    ax4 = py.subplot(121, position=[.05, .1, .35, .7], aspect='equal')
    py.imshow(np.log10(input.medianFrame), aspect='equal', cmap=py.cm.cubehelix)
    py.colorbar(orientation='horizontal')
    py.ylim(py.ylim()[::-1])
    if input.apertureMode[0:4]=='circ':
        tools.drawCircle(input.loc[1], input.loc[0], input.apertures[0], color='lime', fill=False, linewidth=3)
    elif input.apertureMode=='prf':
        py.contour(input.crudeApertureMask, [0.5], colors='lime', linewidths=3)
    py.title('log10(median image)', fontsize=fs)



    py.gcf().text(.5, .95, titstr, fontsize=fs*1.2, horizontalalignment='center')
    ax = py.axis()
    py.plot(input.y, input.x, '.r')
    py.axis(ax)
    for ax in [ax1, ax2,ax3]:
        ax.get_xaxis().set_major_formatter(py.FormatStrFormatter('%i'))
        ax.minorticks_on()
        ax.get_yaxis().set_label_position('right')
        ax.get_yaxis().set_ticks_position('right')
        ax.get_yaxis().set_ticks_position('both')


    rot,sjunk,vjunk = np.linalg.svd(np.cov(input.x, input.y))
    if rot[0,0]<0: rot *= -1
    xp, yp = np.dot(rot, np.vstack((input.x, input.y)))
    if xp.std()==0:
        xp_norm = np.ones(nobs, dtype=float)
    else:
        xp_norm = 2 * ((xp - xp.min()) / (xp.max() - xp.min()) - 0.5)
    xvecs = np.array([xp_norm**n for n in range(input.nordArc)]).T
    ypfit = np.dot(input.arc_fit, xvecs.T)

    py.figure(tools.nextfig(), [10, 5])
    ax1 = py.subplot(121, position=[.1, .15, .35, .75])
    py.plot(input.x, input.y, 'oc', mec='k')
    py.xlabel('X motion [pixels]', fontsize=fs)
    py.ylabel('Y motion [pixels]', fontsize=fs)
    py.minorticks_on()
    ax2 = py.subplot(122, position=[.6, .15, .35, .75])
    py.plot(xp - xp.mean(), yp-ypfit.mean(), 'oc', mec='k')
    py.plot(xp-xp.mean(), ypfit-ypfit.mean(), '.r')
    py.xlabel('Projected X motion [pix]', fontsize=fs)
    py.ylabel('Projected Y motion [pix]', fontsize=fs)
    py.minorticks_on()
    py.text(.95, .05, 'BIC-optimal detrending order: %i' % (input.nordArc-1), transform=ax2.transAxes, horizontalalignment='right', fontsize=fs)
    py.gcf().text(.5, .95, titstr, fontsize=fs*1.2, horizontalalignment='center')

    sss = np.linspace(input.arcLength.min(), input.arcLength.max(), 1000)
    py.figure()
    ax1 = py.subplot(111, position=[.15, .15, .8, .75])
    py.plot(input.arcLength, fluxDetrend, 'or', mec='k')
    py.plot(input.arcLength[input.goodvals], fluxDetrend[input.goodvals], 'oc', mec='k')
    py.plot(input.arcLength, input.decorMotion, '.', color='orange', linewidth=3)
    #errorbar(sbin, fbin, efbin, fmt='ok', ms=10)
    ax = py.axis()
    #[plot([fb]*2, ax[2:], '--k') for fb in fbins]
    py.axis(ax)
    py.xlabel('Arclength [pixels]', fontsize=fs)
    py.ylabel('Detrended Flux', fontsize=fs)
    py.title(titstr, fontsize=fs*1.2)
    py.minorticks_on()
    ax1.get_yaxis().set_major_formatter(py.FormatStrFormatter('%01.4f'))
    py.text(.95, .05, 'BIC-optimal detrending order: %i' % (input.nordPixel1d), transform=ax1.transAxes, horizontalalignment='right', fontsize=fs)


    f0 = np.median(input.rawFlux)
    py.figure()
    ax1 = py.subplot(211, position=[.15, .45, .8, .45])
    py.plot(time, input.decorBaseline * input.decorMotion/f0, '-k')
    py.plot(time, input.rawFlux/f0, 'oc', mec='k')
    py.plot(time[input.noThrusterFiring], (input.rawFlux / input.decorMotion)[input.noThrusterFiring]/f0 - 8*input.rmsCleaned, 'o', mfc='orange', mec='k')
    py.ylabel('Normalized Flux', fontsize=fs)

    py.title(titstr, fontsize=fs*1.2)
    ax2 = py.subplot(212, position=[.15, .1, .8, .3])
    py.plot(time[input.noThrusterFiring], input.cleanFlux[input.noThrusterFiring], 'o', mfc='lime')
    py.plot(py.xlim(), [1,1], '--k')
    #ylim(1.-8*rms, 1.+8*rms)
    ax2.get_yaxis().set_major_formatter(py.FormatStrFormatter('%01.4f'))
    py.xlabel('BJD - 2454833', fontsize=fs)
    py.ylabel('Cleaned Flux', fontsize=fs)
    for ax in [ax1, ax2]:
        ax.get_xaxis().set_major_formatter(py.FormatStrFormatter('%i'))
        ax.minorticks_on()


    # Plot statistics for fit:
    runningStd6 = an.stdfilt(input.cleanFlux[input.goodvals], wid=13)
    RMS6hr = np.median(runningStd6)/np.sqrt(13)
    runningStd2 = an.stdfilt(input.cleanFlux[input.goodvals], wid=5)
    RMS2hr = np.median(runningStd6)/np.sqrt(5)

    if input.apertureMode=='prf':
        fracStr = '%1.4f' % input.prfFrac
    else:
        fracStr = 'None'

    if input.nordGeneralTrend>0:
        trendstr = 'Poly. order, photometric poly:        %i' % input.nordGeneralTrend
    else:
        trendstr = 'Bin size for long-term detrend (days): %1.2f' % (-input.nordGeneralTrend)
    tlines = ['EPIC %i' % input.headers[0]['KEPLERID'], 
              'Kp = %1.2f mag' % input.headers[0]['KEPMAG'],
              'Aperture radii = (%1.2f, %1.2f, %1.2f) pix' % tuple(input.apertures),
              'PRF enclosed fraction = %s' % fracStr,
              'Photometry oversamp = %1.1f' % input.resamp,
              'Poly. order, target motion fit:       %i' % (input.nordArc-1),
              trendstr, 
              'Poly. order, pixel-motion correction: %i' % (input.nordPixel1d-1),
              '', 'Per-point RMS (honest):   %1.1f ppm' % (input.rmsHonest*1e6),
              '', 'Per-point RMS (cleaned):  %1.1f ppm' % (input.rmsCleaned*1e6),
              '2-hour RMS (cleaned):     %1.1f ppm' % (RMS2hr*1e6),
              '6-hour RMS (cleaned):     %1.1f ppm' % (RMS6hr*1e6)]

    #          'Optimal centroiding method employed: %i' % bestInd[0],

    fig, ax = tools.textfig(tlines, fontsize=15)

    return


def errfunc(*arg, **kw):
    """ Generic function to give the chi-squared error on a generic
        function or functions:

    :INPUTS:
       (fitparams, function, arg1, arg2, ... , depvar, weights)

      OR:
       
       (fitparams, function, arg1, arg2, ... , depvar, weights, kw)

      OR:
       
       (allparams, (args1, args2, ..), npars=(npar1, npar2, ...))

       where allparams is an array concatenation of each functions
       input parameters.

      If the last argument is of type dict, it is assumed to be a set
      of keyword arguments: this will be added to errfunc2's direct
      keyword arguments, and will then be passed to the fitting
      function **kw.  This is necessary for use with various fitting
      and sampling routines (e.g., kapteyn.kmpfit and emcee.sampler)
      which do not allow keyword arguments to be explicitly passed.
      So, we cheat!  Note that any keyword arguments passed in this
      way will overwrite keywords of the same names passed in the
      standard, Pythonic, way.


    :OPTIONAL INPUTS:
      jointpars -- list of 2-tuples.  
                   For use with multi-function calling (w/npars
                   keyword).  Setting jointpars=[(0,10), (0,20)] will
                   always set params[10]=params[0] and
                   params[20]=params[0].

      gaussprior -- list of 2-tuples (or None values), same length as "fitparams."
                   The i^th tuple (x_i, s_i) imposes a Gaussian prior
                   on the i^th parameter p_i by adding ((p_i -
                   x_i)/s_i)^2 to the total chi-squared.  Here in
                   :func:`devfunc`, we _scale_ the error-weighted
                   deviates such that the resulting chi-squared will
                   increase by the desired amount.

      uniformprior -- list of 2-tuples (or 'None's), same length as "fitparams."
                   The i^th tuple (lo_i, hi_i) imposes a uniform prior
                   on the i^th parameter p_i by requiring that it lie
                   within the specified "high" and "low" limits.  We
                   do this (imprecisely) by multiplying the resulting
                   deviates by 1e9 for each parameter outside its
                   limits.

      ngaussprior -- list of 3-tuples of Numpy arrays.
                   Each tuple (j_ind, mu, cov) imposes a multinormal
                   Gaussian prior on the parameters indexed by
                   'j_ind', with mean values specified by 'mu' and
                   covariance matrix 'cov.' This is the N-dimensional
                   generalization of the 'gaussprior' option described
                   above. Here in :func:`devfunc`, we _scale_ the
                   error-weighted deviates such that the resulting
                   chi-squared will increase by the desired amount.

                   For example, if parameters 0 and 3 are to be
                   jointly constrained (w/unity means), set: 
                     jparams = np.array([0, 3])
                     mu = np.array([1, 1])
                     cov = np.array([[1, .9], [9., 1]])
                     ngaussprior=[[jparams, mu, cov]]  # Double brackets are key!

      scaleErrors -- bool
                   If True, fit for the measurement uncertainties.
                   In this case, the first element of 'fitparams'
                   ("s") is used to rescale the measurement
                   uncertainties. Thus weights --> weights/s^2, and
                   chi^2 --> 2 N log(s) + chi^2/s^2 (for N data points).  


    EXAMPLE: 
      ::

       from numpy import *
       import phasecurves
       def sinfunc(period, x): return sin(2*pi*x/period)
       snr = 10
       x = arange(30.)
       y = sinfunc(9.5, x) + randn(len(x))/snr
       guess = 8.
       period = optimize.fmin(phasecurves.errfunc,guess,args=(sinfunc,x, y, ones(x.shape)*snr**2))
    """
    # 2009-12-15 13:39 IJC: Created
    # 2010-11-23 16:25 IJMC: Added 'testfinite' flag keyword
    # 2011-06-06 10:52 IJMC: Added 'useindepvar' flag keyword
    # 2011-06-24 15:03 IJMC: Added multi-function (npars) and
    #                        jointpars support.
    # 2011-06-27 14:34 IJMC: Flag-catching for multifunc calling
    # 2012-03-23 18:32 IJMC: testfinite and useindepvar are now FALSE
    #                        by default.
    # 2012-05-01 01:04 IJMC: Adding surreptious keywords, and GAUSSIAN
    #                        PRIOR capability.
    # 2012-05-08 16:31 IJMC: Added NGAUSSIAN option.
    # 2012-10-16 09:07 IJMC: Added 'uniformprior' option.
    # 2013-02-26 11:19 IJMC: Reworked return & concatenation in 'npars' cases.
    # 2013-03-08 12:54 IJMC: Added check for chisq=0 in penalty-factor cases.
    # 2013-04-30 15:33 IJMC: Added C-based chi-squared calculator;
    #                        made this function separate from devfunc.
    # 2013-07-23 18:32 IJMC: Now 'ravel' arguments for C-based function.
    # 2013-10-12 23:47 IJMC: Added 'jointpars1' keyword option.
    # 2014-05-02 11:45 IJMC: Added 'scaleErrors' keyword option..
    # 2014-09-02 19:14 IJMC: Copied from 'phasecurves.py' to 'k2.py'

    params = np.array(arg[0], copy=False)

    if isinstance(arg[-1], dict): 
        # Surreptiously setting keyword arguments:
        kw2 = arg[-1]
        kw.update(kw2)
        arg = arg[0:-1]
    else:
        pass


    if len(arg)==2:
        chisq = errfunc(params, *arg[1], **kw)

    else:
        testfinite = ('testfinite' in kw) and kw['testfinite']
        if not kw.has_key('useindepvar'):
            kw['useindepvar'] = False

        # Keep fixed pairs of joint parameters:
        if kw.has_key('jointpars1'):
            jointpars1 = kw['jointpars1']
            for jointpar1 in jointpars1:
                params[jointpar1[1]] = params[jointpar1[0]]


        if kw.has_key('gaussprior'):
            # If any priors are None, redefine them:
            temp_gaussprior =  kw['gaussprior']
            gaussprior = []
            for pair in temp_gaussprior:
                if pair is None:
                    gaussprior.append([0, np.inf])
                else:
                    gaussprior.append(pair)
        else:
            gaussprior = None

        if kw.has_key('uniformprior'):
            # If any priors are None, redefine them:
            temp_uniformprior =  kw['uniformprior']
            uniformprior = []
            for pair in temp_uniformprior:
                if pair is None:
                    uniformprior.append([-np.inf, np.inf])
                else:
                    uniformprior.append(pair)
        else:
            uniformprior = None

        if kw.has_key('ngaussprior') and kw['ngaussprior'] is not None:
            # If any priors are None, redefine them:
            temp_ngaussprior =  kw['ngaussprior']
            ngaussprior = []
            for triplet in temp_ngaussprior:
                if len(triplet)==3:
                    ngaussprior.append(triplet)
        else:
            ngaussprior = None


        #print "len(arg)>>", len(arg),

        
        if kw.has_key('npars'):
            npars = kw['npars']
            chisq = 0.0
            # Excise "npars" kw for recursive calling:
            lower_kw = kw.copy()
            junk = lower_kw.pop('npars')

            # Keep fixed pairs of joint parameters:
            if kw.has_key('jointpars'):
                jointpars = kw['jointpars']
                for jointpar in jointpars:
                    params[jointpar[1]] = params[jointpar[0]]
                

            for ii in range(len(npars)):
                i0 = sum(npars[0:ii])
                i1 = i0 + npars[ii]
                these_params = arg[0][i0:i1]
                #ret.append(devfunc(these_params, *arg[1][ii], **lower_kw))
                these_params, lower_kw = subfit_kw(arg[0], kw, i0, i1)
                #if 'wrapped_joint_params' in lower_kw:
                #    junk = lower_kw.pop('wrapped_joint_params')
                chisq  += errfunc(these_params, *arg[ii+1], **lower_kw)
                
            return chisq

        else: # Single function-fitting
            depvar = arg[-2]
            weights = arg[-1]

            if not kw['useindepvar']:  # Standard case:
                functions = arg[1]
                helperargs = arg[2:len(arg)-2]
            else:                      # Obsolete, deprecated case:
                functions = arg[1] 
                helperargs = arg[2:len(arg)-3]
                indepvar = arg[-3]



        if testfinite:
            finiteind = isfinite(indepvar) * isfinite(depvar) * isfinite(weights)
            indepvar = indepvar[finiteind]
            depvar = depvar[finiteind]
            weights = weights[finiteind]

        if 'scaleErrors' in kw and kw['scaleErrors']==True:
            if not kw['useindepvar'] or arg[1].__name__=='multifunc' or \
                    arg[1].__name__=='sumfunc':
                model = functions(*((params[1:],)+helperargs))
            else:  # i.e., if useindepvar is True -- old, deprecated usage:
                model = functions(*((params[1:],)+helperargs + (indepvar,)))

            # Compute the weighted residuals:
            if c_chisq:
                chisq = _chi2.chi2(model.ravel(), depvar.ravel(), \
                                       weights.ravel()/params[0]**2)
            else:
                chisq = (weights*((model-depvar)/params[0])**2).sum()
            chisq = chisq/params[0]**2 + 2*depvar.size*np.log(params[0])

        else:
            if not kw['useindepvar'] or arg[1].__name__=='multifunc' or \
                    arg[1].__name__=='sumfunc':
                model = functions(*((params,)+helperargs))
            else:  # i.e., if useindepvar is True -- old, deprecated usage:
                model = functions(*((params,)+helperargs + (indepvar,)))

            # Compute the weighted residuals:
            if c_chisq:
                chisq = _chi2.chi2(model.ravel(), depvar.ravel(), \
                                       weights.ravel())
            else:
                chisq = (weights*(model-depvar)**2).sum()
            

        # Compute 1D and N-D gaussian, and uniform, prior penalties:
        additionalChisq = 0.
        if gaussprior is not None:
            
            additionalChisq += np.sum([((param0 - gprior[0])/gprior[1])**2 for \
                                   param0, gprior in zip(params, gaussprior)])

        if ngaussprior is not None:
            for ind, mu, cov in ngaussprior:
                dvec = params[ind] - mu
                additionalChisq += \
                    np.dot(dvec.transpose(), np.dot(np.linalg.inv(cov), dvec))

        if uniformprior is not None:
            for param0, uprior in zip(params, uniformprior):
                if (param0 < uprior[0]) or (param0 > uprior[1]):
                    chisq *= 1e9

        # Scale up the residuals so as to impose priors in chi-squared
        # space:
        chisq += additionalChisq
    
    return chisq

def xcorrStack(stack, npix_corr=4, plotalot=False, maxshift=np.inf):
    """
    Cross-correlation stack
    
    Return x and y motions determined via 1D cross-correlation of image stack.
    
   :INPUTS:
      stack : 3D numpy array (M x N x N)
        first frame (stack[0]) is the reference image.

      npix_corr : int
         Radius for correlations to measure image motions

    :OUTPUTS:
      dx, dy : tuple of 1D arrays
    """
    # 2011-12-28 19:25 IJMC: Created
    # 2012-06-17 22:06 IJMC: Added plotalot and maxshift flags
    # 2014-09-02 19:21 IJMC: Moved from 'dophot.py' into 'k2.py'

    if plotalot:
        import pylab as py

    nimg, npix, npiy = stack.shape

    # Sum along both axes of image
    sx = stack.mean(1)  
    sy = stack.mean(2)  

    # Subtract of mean values
    sx0 = sx[0] - sx[0].mean()
    sy0 = sy[0] - sy[0].mean()


    dx = np.zeros(nimg)
    dy = np.zeros(nimg)
    corrCoordx = np.arange(npix) - npix/2 # Array of lags along x
    corrCoordy = np.arange(npiy) - npiy/2 # Array of lags along y
    valid_index = np.abs(corrCoordx) <= maxshift
    valid_indey = np.abs(corrCoordy) <= maxshift
    for ii in range(nimg):
        if np.isfinite(sx[ii]).all() and  np.isfinite(sy[ii]).all():
            
            # Sum along both axes frame
            sxii = sx[ii] - sx[ii].mean()
            syii = sy[ii] - sy[ii].mean()

            corry = np.correlate(sx0,sxii, mode='same', old_behavior=False)
            corrx = np.correlate(sy0,syii, mode='same', old_behavior=False)

            x_guess = corrCoordx[valid_index][(corrx[valid_index]==corrx[valid_index].max())]
            y_guess = corrCoordy[valid_indey][(corry[valid_indey]==corry[valid_indey].max())]

            if np.abs(x_guess) > maxshift:
                x_guess = maxshift * np.sign(x_guess)
            if np.abs(y_guess) > maxshift:
                y_guess = maxshift * np.sign(y_guess)

            # Fit peak of the cross-correlation peak with polynomial to determine displacement
            x_ind = np.abs(corrCoordx - x_guess) < npix_corr
            y_ind = np.abs(corrCoordy - y_guess) < npix_corr
            xfit = np.polyfit(corrCoordx[x_ind], corrx[x_ind], 2)
            yfit = np.polyfit(corrCoordy[y_ind], corry[y_ind], 2)
            dx[ii] = -0.5 * xfit[1] / xfit[0]
            dy[ii] = -0.5 * yfit[1] / yfit[0]
            if np.abs(dx[ii]) > maxshift:
                dx[ii] = maxshift * np.sign(dx[ii])
            if np.abs(dy[ii]) > maxshift:
                dy[ii] = maxshift * np.sign(dy[ii])

            if plotalot:
                py.figure()
                py.plot(corrCoordx[x_ind], corrx[x_ind], 'ob', label='x')
                py.plot(corrCoordy[y_ind], corry[y_ind], 'dr', label='y')
                py.plot(corrCoordx[x_ind], np.polyval(xfit, corrCoordx[x_ind]), '--b')
                py.plot(corrCoordy[y_ind], np.polyval(yfit, corrCoordy[y_ind]), '--r')
        else:
            dx[ii] = 0
            dy[ii] = 0

    return dx, dy


def loadPRF(**kw):
    """Load a Kepler PRF appropriate for the specified location.

    :INPUTS:
      file : str
        Name of a Kepler pixel target file. The headers should contain
        all necessary data.  Otherwise, you need to input module,
        output, and coordinate values.

      module : int
        The CCD module of the detector used for these
        observations. Any of 2-24 (inclusive), excepting 5 & 21.

      output : int
        The CCD output used for these observations. Any of 1-4
        (inclusive).

      loc : 2-sequence of ints
        Location of target on the CCD.  This would correspond to
        (CRVAL1P, CRVAL2P) in the FITS header.
        
      _prfpath : str
        Path of the Kepler PRF files (available from
        http://archive.stsci.edu/kepler/fpc.html). Default is
        '~/proj/transit/kepler/prf/'

    :RETURNS:
      (prf, sampling)

    :EXAMPLE:
      ::

       import k2
       prf, sampling = k2.loadPRF(file=kplr060018142-2014044044430_lpd-targ.fits)

    """
    # 2014-09-03 17:50 IJMC: Created

    # Parse inputs:
    if 'file' in kw:
        file = kw['file']
    else:
        file = None
    if 'module' in kw:
        module = kw['module']
    else:
        module = None
    if 'output' in kw:
        output = kw['output']
    else:
        output = None
    if 'loc' in kw:
        xcen, ycen = kw['loc']
    else:
        loc = None
    if '_prfpath' in kw:
        _prfpath = kw['_prfpath']
    else:
        _prfpath = '' + prfpath()

    if file is not None:
        f = pyfits.open(file, mode='readonly')
        module = f[0].header['module']
        output = f[0].header['output']
        xcen = f[2].header['crval1p']
        ycen = f[2].header['crval2p']
        f.close()

    # Load the PRF FITS file:
    f = pyfits.open(_prfpath + 'kplr%02i.%i_2011265_prf.fits' % (module, output), mode='readonly')

    # Determine which PRF location to load (there are 5)
    #x0s = np.array([12, 12, 1111, 1111, 549.5])
    #y0s = np.array([20, 1043, 1043, 20, 511.5])
    x0s = np.array([el.header['crval1p'] for el in f[1:]])
    y0s = np.array([el.header['crval2p'] for el in f[1:]])
    dist = np.sqrt((x0s - xcen)**2 + (y0s - ycen)**2)
    best3 = (dist <= np.sort(dist)[3]).nonzero()[0][0:3]
    prfWeights = 1./(dist[best3] + 1)
    prfWeights /= prfWeights.sum()

    # Construct the appropriately-weighted PRF:
    prf = 0
    for ii in range(3):
        prf += prfWeights[ii] * f[1+best3[ii]].data

    sampling = 1./f[1].header['cdelt1p']
    f.close()

    return prf, sampling

def refineCentroid(frame, apertures, loc=None, mask=None, maxiter=np.inf, loctol=0.1, verbose=False):
    """Find (or refine) centroid position for a data frame.

    :INPUTS:
      frame : 2D NumPy array
         data frame of interest

      apertures : 2D NumPy array
        If a 3-sequence, this indicates the *radii* of three circular apertures.

      loc : 2-sequence or None
         Initial guess for the indexing coordinates of the region of
         interest.

      mask : 2D NumPy array, or None
        Boolean mask; True for pixels of 'frame' to use, False for
        pixels to be ignored.

      maxiter : scalar
        Centroid refinement will stop after 'maxiter' iterations.

    :RETURNS:
      newloc : 2-sequence

    :NOTES:
      Uses :func:`phot.aperphot` to estimate backgrounds and generate masks.
         """
    # 2014-09-04 14:53 IJMC: Created
    # 2014-09-08 10:18 IJMC: Improved masking for K2 C0 data, and NaNs.

    if verbose: print "Refining centroid position:"
    maxlim = max(frame.shape)
    x1d, y1d = np.arange(frame.shape[1]), np.arange(frame.shape[0])
    xx, yy = np.meshgrid(x1d, y1d)
    
    if loc is None:
        newloc = [(-9e99, -9e99)]
    else:
        newloc = np.array(loc, copy=True)

    oldloc = newloc - 99
    locHist = [(-1,-1)]
    iter = 0


    if len(apertures)==3:
        dap = np.array(apertures) * 2.
        mask = None
    else:
        dap = None
        mask = apertures

    #badvals = True - np.isfinite(frame)
    #bfixpix(frame, badvals)
    phot0 = phot.aperphot(frame, pos=newloc, dap=dap, mask=mask, resamp=1, retfull=True)
    while np.abs(oldloc - newloc).max()>loctol and not (tuple(newloc) in locHist[0:-1]) and iter<maxiter:
        oldloc = newloc.copy()
        xcen = np.array(((frame-phot0.bg) * xx)[phot0.mask_targ].sum()/((frame-phot0.bg)[phot0.mask_targ]).sum())
        ycen = np.array(((frame-phot0.bg) * yy)[phot0.mask_targ].sum()/((frame-phot0.bg)[phot0.mask_targ]).sum())
        xcen = min(max(xcen, 0), maxlim)
        ycen = min(max(ycen, 0), maxlim)
        newloc = np.array([ycen,xcen], copy=True)
        phot0 = phot.aperphot(frame, pos=newloc, dap=dap, mask=mask, resamp=1, retfull=True)
        if verbose: print "  New centroid location is: " + str(newloc)
        loc = tuple(newloc)
        locHist.append(tuple(newloc))

    if verbose and iter==maxiter:
        print "Reached maximum number of iterations (%i) before converging on a centroid." % maxiter
    
    return loc




def fitPhotometryFromPixelData(fn, stack, loc, apertures, errstack=None, recentroid=True, verbose=False, pool=None, nthreads=None, retfull=False):
    """
    :INPUTS:
      fn : string
        Filename of the target pixel file (passed to :func:`loadPRF`)
      
      stack : 2D or 3D NumPy array.
        Stack of pixel data, e.g. from :func:`loadPixelFile`
      
      loc: 2-sequence
        indexing coordinates of target. Need not be integers, but if
        converted to int these would index the approximate location of
        the target star.
  
        If loc is None, just use the brightest pixel. This is dangerous!
  
      apertures : various
        If a 3-sequence, this indicates the *radii* of three circular apertures.
  
        Otherwise, we'll have to think of something fancier to do.

      errstack : 2D or 3D NumPy array.
        Optional stack of data uncertainties.
  
    :RETURNS:
      flux, background, x, y, chisq

    :NOTES:
      May have problems for data whose motions are comparable to or
      larger than the PSF size.

      Relies on :func:`phot.prffit`
      """
    # 2014-08-27 16:25 IJMC: Created
  
    if verbose: print "Starting PRF-fitting photometry"

    # Parse inputs:
    if stack.ndim==2:
        stack = stack.reshape((1,)+stack.shape)

    nobs = stack.shape[0]
    if errstack is None:
        errstack = np.ones(stack.shape)
    elif errstack.ndim==2:
        errstack = np.reshape((1,)+errstack.shape)

    frame0 = np.median(stack, axis=0)
    if loc is None:
        loc = (frame0==frame0.max()).nonzero()

    apertures = np.array(apertures)
    if len(apertures)==3:
        dap = np.array(apertures)*2
        mask = None
    elif apertures.shape==stack.shape or apertures.shape==frame0.shape:
        dap = None
        mask = apertures

    userPool = False
    if pool is not None:
        nthreads = pool._processes
        userPool = True
    elif nthreads>1:
        pool = Pool(processes=nthreads)


    stack0 = np.median(stack, axis=0)
    if recentroid:
        loc = refineCentroid(stack0, apertures, loc=loc, mask=None, verbose=verbose)

    prf, sampling = loadPRF(file=fn)
    #loc = (33, 23)
    #sampling = 50
    dframe = apertures[0]*2+1


    weights = 1./errstack**2
   
    ngrid = 100
    gridpts = np.linspace(-apertures[0],apertures[0],ngrid)*sampling

    # First, run for stack median:
    weights0 = np.median(weights, axis=0)
    testgrid = phot.psffit(prf, stack0, loc, weights0, scale=sampling, dframe=dframe, xoffs=gridpts, yoffs=gridpts, verbose=verbose-1)
    guess = testgrid[5:7]
    fitargs = (prf, stack0, weights0, sampling, dframe, loc, False)
    medianFit = an.fmin(phot.psffiterr, guess, args=fitargs, xtol=0.5, ftol=0.1, full_output=True, nonzdelt=2)
    #mod = phot.psffit(prf, image, loc, weights, scale=sampling, dframe=dframe, xoffs=[fit[0][0]], yoffs=[fit[0][1]], verbose=True)
    
    
    # Iterate over all frames:
    fitx = np.zeros(nobs, dtype=float)
    fity = np.zeros(nobs, dtype=float)
    flux = np.zeros(nobs, dtype=float)
    chisq = np.zeros(nobs, dtype=float)
    bg = np.zeros(nobs, dtype=float)
    test_kw = dict(full_output=True, disp=False, ftol=0.1, xtol=0.5)
    
    HUGEfitargs = [[phot.psffiterr, medianFit[0], (prf, stack[ii], weights[ii], sampling, dframe, loc, False), test_kw] for ii in xrange(nobs)]
    if nthreads==1:
        allfits =      map(an.fmin_helper2, HUGEfitargs)
    else:
        allfits = pool.map(an.fmin_helper2, HUGEfitargs)
        if not userPool:
            pool.close()
            pool.join()

    # Extract the fit parameters:
    for ii in xrange(nobs):
        fit = allfits[ii]
        model = phot.psffit(prf, stack[ii], loc, weights[ii], scale=sampling, dframe=dframe, xoffs=[fit[0][0]], yoffs=[fit[0][1]], verbose=verbose-1)
        fitx[ii], fity[ii] = fit[0]
        chisq[ii], bg[ii], flux[ii] = model[-3:]

    

    ret = flux, bg, loc[0]-fitx/sampling, loc[1]-fity/sampling, chisq

    if retfull:
        chis = np.array([phot.psffit(prf, stack[ii], loc, weights[ii], scale=sampling, dframe=dframe, xoffs=[allfits[ii][0][0]], yoffs=[allfits[ii][0][1]], verbose=False)[2] for ii in xrange(nobs)])
        dats = np.array([phot.psffit(prf, stack[ii], loc, weights[ii], scale=sampling, dframe=dframe, xoffs=[allfits[ii][0][0]], yoffs=[allfits[ii][0][1]], verbose=False)[1] for ii in xrange(nobs)])
        models = np.array([phot.psffit(prf, stack[ii], loc, weights[ii], scale=sampling, dframe=dframe, xoffs=[allfits[ii][0][0]], yoffs=[allfits[ii][0][1]], verbose=False)[0] for ii in xrange(nobs)])
        ret = ret + (dats,models, chis)

    return ret


def generatePRFaperture(fn, frame, loc, apertures, frac, eframe=None, recentroid=True, verbose=False, pool=None, nthreads=None, retfull=False, kepmask=None):
    """Generate a binary mask that encloses 'frac' of the Kepler PRF.

    :INPUTS:
      fn : string
        Filename of the target pixel file (passed to :func:`loadPRF`)
      
      frame : 2D NumPy array.
        A reference frame (e.g., the mean of a stack of frames)
      
      loc: 2-sequence
        indexing coordinates of target. Need not be integers, but if
        converted to int these would index the approximate location of
        the target star.
  
        If loc is None, just use the brightest pixel. This is dangerous!
  
      apertures : various
        If a 3-sequence, this indicates the *radii* of three circular
        apertures. Here, only the first is used -- to indicate the
        region within which to search for the desired target.
  
        Otherwise, we'll have to think of something fancier to do.

      frac : scalar, 0 <= frac <= 1
        The desired fraction of PRF energy to include in the mask.
  
      eframe : 2D NumPy array.
        Optional stack of 'frame' uncertainties.
  
      kepmask : 2D NumPy array
        Optional binary mask of good and bad pixels.

    :RETURNS:
      apertureMask (for :func:`phot.aperphot`) -- equal to '1' inside
      target aperture and '2' in sky annulus.

    :NOTES:
      Relies on :func:`phot.prffit`
    """
    # 2014-09-05 21:14 IJMC: Created
    # 2014-09-08 13:37 IJMC: Added 'kepmask' option to avoid obvious nans.

    # Parse inputs:
    if eframe is None:
        weights = np.ones(frame.shape)
    else:
        weights = 1./eframe**2


    if loc is None:
        loc = (frame==frame.max()).nonzero()

    apertures = np.array(apertures)
    if len(apertures)==3:
        dap = np.array(apertures)*2
        mask = None
    elif apertures.shape==stack.shape or apertures.shape==frame0.shape:
        dap = None
        mask = apertures

    if recentroid:
        loc = refineCentroid(frame, apertures, loc=loc, mask=None, verbose=verbose)

    prf, sampling = loadPRF(file=fn)
    #loc = (33, 23)
    dframe = apertures[0]*2+1
    if kepmask is not None:
        badmask = (True - kepmask) + (True - np.isfinite(frame))
        bfixpix(frame, badmask)
    
   
    ngrid = 50
    gridpts = np.linspace(-apertures[0],apertures[0],ngrid)*sampling

    # First, run for stack median:
    testgrid = phot.psffit(prf, frame, loc, weights, scale=sampling, dframe=dframe, xoffs=gridpts, yoffs=gridpts, verbose=verbose-1)
    guess = testgrid[5:7]
    fitargs = (prf, frame, weights, sampling, dframe, loc, False)
    medianFit = an.fmin(phot.psffiterr, guess, args=fitargs, xtol=0.5, ftol=0.1, full_output=True, nonzdelt=2, disp=verbose)
    
    modelOut = phot.psffit(prf, frame, loc, weights, scale=sampling, dframe=dframe, xoffs=[medianFit[0][0]], yoffs=[medianFit[0][1]], verbose=verbose)

    
    modelPRF = (modelOut[0] - modelOut[-2]) / modelOut[-1]
    
    corr = signal.correlate2d(frame, modelOut[1], mode='same')
    yvals = np.arange(frame.shape[0])
    xvals = np.arange(frame.shape[1])
    yy,xx = np.meshgrid(xvals, yvals)
    searchrad = np.sqrt((xx - loc[0])**2 + (yy - loc[1])**2) < apertures[0]
    subloc = ((corr*searchrad)==(corr*searchrad).max()).nonzero()

    do2 = int(np.floor(dframe/2))  # apertures[0]
    newframe = np.zeros(frame.shape, dtype=float)
    newframe[subloc[0]-do2:subloc[0]+do2+1, subloc[1]-do2:subloc[1]+do2+1] = modelPRF

    targMask = newframe > an.confmap(newframe, frac)


    # Now generate the sky mask:
    kernWid = np.diff(apertures)
    xsm0 = np.arange(-kernWid[0], kernWid[0]+1)
    xsm1 = np.arange(-kernWid[1], kernWid[1]+1)
    xx0,yy0 = np.meshgrid(xsm0, xsm0)
    xx1,yy1 = np.meshgrid(xsm1, xsm1)
    rr0 = (np.sqrt(xx0**2 + yy0**2) <= kernWid[0]) + 0.
    rr1 = (np.sqrt(xx1**2 + yy1**2) <= kernWid[1]) + 0.
    skyInner = signal.convolve2d(targMask, rr0, mode='same') > 0
    skyOuter = signal.convolve2d(skyInner, rr1, mode='same') > 0
    skyAnnulus = skyOuter - skyInner

    return 0. + targMask + 2*skyAnnulus

def bfixpix(data, badmask, n=4, retdat=False):
    """Replace pixels flagged as nonzero in a bad-pixel mask with the
    average of their nearest four good neighboring pixels.

    :INPUTS:
      data : numpy array (two-dimensional)

      badmask : numpy array (same shape as data)

    :OPTIONAL_INPUTS:
      n : int
        number of nearby, good pixels to average over

      retdat : bool
        If True, return an array instead of replacing-in-place and do
        _not_ modify input array `data`.  This is always True if a 1D
        array is input!

    :RETURNS: 
      another numpy array (if retdat is True)

    :TO_DO:
      Implement new approach of Popowicz+2013 (http://arxiv.org/abs/1309.4224)
    """
    # 2010-09-02 11:40 IJC: Created
    #2012-04-05 14:12 IJMC: Added retdat option
    # 2012-04-06 18:51 IJMC: Added a kludgey way to work for 1D inputs
    # 2012-08-09 11:39 IJMC: Now the 'n' option actually works.
    # 2014-09-08 13:35 IJMC: Moved from nsdata.py to k2.py

    if data.ndim==1:
        data = np.tile(data, (3,1))
        badmask = np.tile(badmask, (3,1))
        ret = bfixpix(data, badmask, n=2, retdat=True)
        return ret[1]


    nx, ny = data.shape

    badx, bady = np.nonzero(badmask)
    nbad = len(badx)

    if retdat:
        data = np.array(data, copy=True)
    
    for ii in range(nbad):
        thisloc = badx[ii], bady[ii]
        rad = 0
        numNearbyGoodPixels = 0

        while numNearbyGoodPixels<n:
            rad += 1
            xmin = max(0, badx[ii]-rad)
            xmax = min(nx, badx[ii]+rad)
            ymin = max(0, bady[ii]-rad)
            ymax = min(ny, bady[ii]+rad)
            x = np.arange(nx)[xmin:xmax+1]
            y = np.arange(ny)[ymin:ymax+1]
            yy,xx = np.meshgrid(y,x)
            #print ii, rad, xmin, xmax, ymin, ymax, badmask.shape
            
            rr = np.abs(xx + 1j*yy) * (1. - badmask[xmin:xmax+1,ymin:ymax+1])
            numNearbyGoodPixels = (rr>0).sum()
        
        closestDistances = np.unique(np.sort(rr[rr>0])[0:n])
        numDistances = len(closestDistances)
        localSum = 0.
        localDenominator = 0.
        for jj in range(numDistances):
            localSum += data[xmin:xmax+1,ymin:ymax+1][rr==closestDistances[jj]].sum()
            localDenominator += (rr==closestDistances[jj]).sum()

        #print badx[ii], bady[ii], 1.0 * localSum / localDenominator, data[xmin:xmax+1,ymin:ymax+1]
        data[badx[ii], bady[ii]] = 1.0 * localSum / localDenominator

    if retdat:
        ret = data
    else:
        ret = None

    return ret


if __name__ == "__main__":
    sys.exit(main())


