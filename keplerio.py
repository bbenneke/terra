"""
Functions for facilitating the reading and writing of Kepler files.

Load a Quarter
--------------

>>> tQ = keplerio.qload(file)

Load mulitple quarters
----------------------
>>> tLCset = map(keplerio.qload,files)
>>> tLC    = keplerio.sQ(tLCset)

"""
import numpy as np
from numpy import ma
from scipy.interpolate import UnivariateSpline
from scipy import ndimage as nd
import copy
import atpy
import os
import sys
import tarfile
import glob
import pyfits
import sqlite3

from matplotlib.mlab import csv2rec
import keptoy
import detrend
import tfind

kepdir = os.environ['KEPDIR']
kepdat = os.environ['KEPDAT']
cbvdir = os.path.join(kepdir,'CBV/')
kepfiles = os.path.join(os.environ['KEPBASE'],'files')
qsfx = csv2rec(os.path.join(kepfiles,'qsuffix.txt'),delimiter=' ')
kicdb = os.path.join(kepfiles,'KIC.db')

# Extra columns not needed in transit search.
xtraCol = ['TIMECORR','SAP_BKG','SAP_BKG_ERR',
           'PSF_CENTR1','PSF_CENTR1_ERR','PSF_CENTR2',
           'PSF_CENTR2_ERR','MOM_CENTR1','MOM_CENTR1_ERR','MOM_CENTR2',
           'MOM_CENTR2_ERR','POS_CORR1','POS_CORR2']

###########
# File IO #
###########

def KICPath(KIC, QL=range(1,9) ):
    pathL = []
    for Q in QL:
        tQ = qsfx[ np.where(qsfx['q'] == Q) ]
        path = 'Q%i/kplr%09d-%s_llc.fits' % ( Q,KIC,tQ.suffix[0] ) 
        path = 'archive/data3/privkep/EX/' + path
        pathL.append(path)
    return pathL

def tarXL(filesL):
    """
    Extract List of files from tar archive.
    """
    qfunc = lambda s : int(s.split('Q')[1].split('/kplr')[0])
    QL = map(qfunc,filesL)
    t = atpy.Table()
    t.add_column('file',filesL)
    t.add_column('Q',QL)
    for q in np.unique(QL):
        tQ = t.where(t.Q == q)
        tar  = os.path.join(kepdat,'EX_Q%i.tar' % q)
        nload = 0
        nfail = 0

        try:
            tar  = tarfile.open(tar)
            for file in tQ.data['file']:
                try:
                    tar.extract(file)
                    print "Extracted %s" % file
                    nload +=1 
                except KeyError:
                    print sys.exc_info()[1]
                    nfail +=1
            tar.close()
            print "Loaded %i, Failed %i" %(nload,nfail)
        except IOError:
            print sys.exc_info()[1]

def qload(file,allCol=False):
    """
    Quarter Load

    Takes the fits file from the Kepler team and outputs an atpy table.

    Parameters
    ----------
    file : Path to the .fits file.

    Returns
    -------
    t    : atpy table

    """
    hdu = pyfits.open(file)
    t = atpy.Table(file,type='fits')  
    if allCol is False:
        t.remove_columns(xtraCol)


    t.rename_column('TIME','t')
    t.rename_column('CADENCENO','cad')

    kw = ['NQ','CUT','OUTREG']
    
    # Keywords to extract from the .fits header.
    hkw = ['QUARTER','MODULE','CHANNEL','OUTPUT','SKYGROUP',
           'RA_OBJ'  # [deg] right ascension                          
           ,'DEC_OBJ' # [deg] declination                              
           ,'EQUINOX' # equinox of celestial coordinate system         
           ,'PMRA'    # [arcsec/yr] RA proper motion                   
           ,'PMDEC'   # [arcsec/yr] Dec proper motion                  
           ,'PMTOTAL' # [arcsec/yr] total proper motion                
           ,'GLON'    # [deg] galactic longitude                       
           ,'GLAT'    # [deg] galactic latitude                        
           ,'GMAG'    # [mag] SDSS g band magnitude                    
           ,'RMAG'    # [mag] SDSS r band magnitude                    
           ,'JMAG'    # [mag] J band magnitude from 2MASS              
           ,'HMAG'    # [mag] H band magnitude from 2MASS              
           ,'KMAG'    # [mag] K band magnitude from 2MASS              
           ,'KEPMAG'  # [mag] Kepler magnitude (Kp) 
           ]

    t.add_keyword('PATH',file)

    for k in kw:
        t.keywords[k] = False

    for k in hkw:
        t.keywords[k] = hdu[0].header[k]


    t.keywords.pop('TIERABSO') # Problems with conversion

    update_column(t,'q',np.zeros(t.data.size) + t.keywords['QUARTER'] )
    t.table_name = 'Q%i' % t.keywords['QUARTER']

    t = nQ(t)
    t = nanTime(t)
    return t

############################
# Quarter-level processing #
############################

def nQ(t0):
    """
    Normalize lightcurve.

    Parameters
    ----------
    t0 : input table.

    Returns
    -------
    t  : Table with new, normalized columns.
    
    """
    t = copy.deepcopy(t0)

    col   = ['SAP_FLUX','PDCSAP_FLUX']
    ecol  = ['SAP_FLUX_ERR','PDCSAP_FLUX_ERR']
    col2  = ['f','fpdc']   # Names for the modified columns.
    ecol2 = ['ef','efpdc']

    for c,ec,c2,ec2 in zip(col,ecol,col2,ecol2):
        update_column(t,c2, copy.deepcopy(t[c]) )
        update_column(t, ec2, copy.deepcopy(t[ec]) )
        medf = np.median(t[c])
        t.data[c2]  =  t.data[c2]/medf - 1
        t.data[ec2] =  t.data[ec2]/medf

    t.keywords['NQ'] = True

    return t

def nanTime(t0):
    """
    Remove nans from the timeseries.

    Parameters
    ----------
    t0 : input table.

    Returns
    -------
    t  : Table with new, normalized columns.
    
    """
    t = copy.deepcopy(t0)
    tm = ma.masked_invalid(t.t)
    cad,t.t = detrend.maskIntrp(t.cad,tm)

    return t

def sQ(tLCset0):
    """
    Stitch Quarters together.

    Fills in missing times and cadences with their proper values.  It
    assigns placeholder values for other columns.
    - floats --> nan
    - bools  --> True

    Parameters
    ----------
    tLCset0 : List of tables to stitch together.
    
    Returns
    -------
    tLC : Lightcurve that has been stitched together.    

    """

    tLCset = copy.deepcopy(tLCset0)
    tLC = atpy.Table()
    tLC.table_name = "LC" 
    tLC.keywords = tLCset[0].keywords

    # Figure out which cadences are missing and fill them in.
    cad       = [tab.cad for tab in tLCset]
    cad       = np.hstack(cad) 
    cad,iFill = cadFill(cad)
    nFill     = cad.size
    update_column(tLC,'cad',cad)

    # Add all the columns from the FITS file.
    fitsname = tLCset[0].data.dtype.fields.keys()
    fitsname.remove('cad')

    for fn in fitsname:
        col = [tab[fn] for tab in tLCset] # Column in list form
        col = np.hstack(col)       

        # Fill new array elements
        if col.dtype is np.dtype('bool'):
            fill_value = True
        else:
            fill_value = np.nan

        ctemp = np.empty(nFill,dtype=col.dtype) # Temporary column
        ctemp[::] = fill_value
        ctemp[iFill] = col
        update_column(tLC,fn,ctemp)

    # nanTime doesn't work here because I've update the "cad" field
    tm = ma.masked_invalid(tLC.t)
    cad,tLC.t = detrend.maskIntrp(tLC.cad,tm)

    return tLC

def cadFill(cad0):
    """
    Cadence Fill

    We want the elements of the arrays to be evenly sampled so that
    phase folding is equivalent to array reshaping.

    Parameters
    ----------
    cad : Array of cadence identifiers.
    
    Returns
    -------
    cad   : New array of cadences (without gaps).
    iFill : Indecies that were not missing.

    """
    bins = np.arange(cad0[0],cad0[-1]+2)
    count,cad = np.histogram(cad0,bins=bins)
    iFill = np.where(count == 1)[0]
    
    return cad,iFill


def iscadFill(t,f):
    """
    Is the time series evenly spaced.

    The vectorized implementation of LDMF depends on the data being
    evenly sampled.  This function checks the time between cadances.
    If this is more than a small fraction of the cadence length,
    fail!
    """

    tol = keptoy.lc/100. 
    return ( (t[1:] - t[:-1]).ptp() < tol ) & (t.size == f.size)

def update_column(t,name,value):
    try:
        t.add_column(name,value)
    except ValueError:
        t.remove_columns([name])
        t.add_column(name,value)


def idQ2mo(id,q):
    """
    Quarter plus KIC ID to mod out.

    Load query the KIC.db and return Module and Output for a given quarter.
    """

    
    con = sqlite3.connect(kicdb)
    cur = con.cursor()
    command = 'SELECT m,o from q%i WHERE id==%i' % (q,id)
    res = cur.execute(command).fetchall()
    assert len(res)==1,"KIC ID is not unique"
    con.close()
    m,o = res[0]
    return m,o
