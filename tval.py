"""
Transit Validation

After the brute force period search yeilds candidate periods,
functions in this module will check for transit-like signature.
"""
import numpy as np
from numpy import ma

from scipy import optimize
import scipy.ndimage as nd
import detrend
import sys

import glob
import copy
import atpy
import qalg
import keptoy
import tfind

def trsh(P,tbase):
    ftdurmi = 0.5
    tdur = keptoy.a2tdur( keptoy.P2a(P) ) 
    tdurmi = ftdurmi*tdur 
    dP     = tdurmi * P / tbase
    depoch = tdurmi

    return dict(dP=dP,depoch=depoch)

def objMT(p,time,fdt,p0,dp0):
    """
    Multitransit Objective Function

    With a prior on P and epoch

    """
    fmod = keptoy.P05(p,time)
    resid = (fmod - fdt)/1e-4
    obj = (resid**2).sum() + (((p0[0:2] - p[0:2])/dp0[0:2])**2 ).sum()
    return obj

def obj1T(p,t,f,P,p0,dp0):
    """
    Single Transit Objective Function
    """
    model = keptoy.P051T(p,t,P)
    resid  = (model - f)/1e-4
    obj = (resid**2).sum() + (((p0[0:2] - p[0:2])/dp0[0:2])**2 ).sum()
    return obj


def obj1Tlin(pNL,t,f):
    """
    Single Transit Objective Function.  For each trial value of epoch
    and width, we determine the best fit by linear fitting.

    Parameters
    ----------
    pNL  - The non-linear parameters [epoch,tdur]
   
    """
    pL = linfit1T(pNL,t,f)
    pFULL = np.hstack( (pNL[0],pL[0],pNL[1],pL[1:]) )
    model = keptoy.P051T(pFULL,t)

    resid  = (model - f)/1e-4
    obj = (resid**2).sum() 
    return obj


def linfit1T(p,t,f):
    """
    Linear fit to 1 Transit.

    Depth and polynomial cofficents are linear

    Parameters
    ----------
    p : [epoch,tdur]
    t : time
    f : flux

    Returns
    -------
    p1 : Best fit [df,pleg0,pleg1...] from linear fitting.
    """
    
    ndeg=3

    epoch  = p[0]
    tdur   = p[1]

    # Construct polynomial design matrix
    trendDS = [] 
    for i in range(ndeg+1):
        pleg = np.zeros(ndeg+1)
        pleg[i] = 1
        trendDS.append( keptoy.trend(pleg,t) )
    trendDS = np.vstack(trendDS)

    # Construct lightcurve design matrix
    plc = np.hstack(( epoch,1.,tdur,list(np.zeros(ndeg+1)) ))
    lcDS = keptoy.P051T(plc,t)

    DS = np.vstack((lcDS,trendDS))
    p1 = np.linalg.lstsq(DS.T,f)[0]

    return p1

def fit1T(pNL0,t,f):
    """
    Fit Single transit
    """
    pNL = optimize.fmin(obj1Tlin,pNL0,args=(t,f))
    pL = linfit1T(pNL,t,f)
    pFULL = np.hstack( (pNL[0],pL[0],pNL[1],pL[1:]) )
    return pFULL

def LDT(t,fm,p,wd=2.):
    """
    Local detrending.  
    At each putative transit, fit a model transit and continuum lightcurve.

    Parameters
    ----------

    t  : Times (complete data string)
    f  : Flux (complete data string)
    p  : Parameters {'P': , 'epoch': , 'tdur': }

    """
    P     = p['P']
    epoch = p['epoch']
    tdur  = p['tdur']

    Pcad     = round(P/keptoy.lc)
    epochcad = round(epoch/keptoy.lc)
    tdurcad  = round(tdur/keptoy.lc)
    wdcad    = round(wd/keptoy.lc)

    dM = tfind.mtd(t,fm.filled(),tdurcad)
    dM.mask = fm.mask | ~tfind.isfilled(t,fm,tdurcad)

    tm   = ma.masked_array(t,copy=True,mask=fm.mask)
    ### Determine the indecies of the points to fit. ###
    # Exclude regions where the convolution returned a nan.
    ms   = midTransId(t,p)
    ms   = [m for m in ms if ~dM.mask[m] ]
    sLDT = [ getSlice(m,wdcad) for m in ms ]
    x = np.arange(dM.size)
    idL  = [ x[s][np.where(~fm[s].mask)] for s in sLDT ]

    func = lambda m,id : fit1T( [t[m],tdur], tm[id].data , fm[id].data) 
    p1L = map(func,ms,idL)

    fdt   = ma.masked_array(fm,copy=True,mask=True)
    tdt   = ma.masked_array(tm,copy=True,mask=True)
    trend = ma.masked_array(fm,copy=True,mask=True)
    ffit  = ma.masked_array(fm,copy=True,mask=True)


    for p1,id in zip(p1L,idL):
        trend[id] = keptoy.trend(p1[3:], t[id]).astype('>f4')
        ffit[id]  = keptoy.P051T(p1, t[id]).astype('>f4')
        fdt[id]   = fm[id] - trend[id] 

        trend[id].mask = False
        ffit[id].mask  = False
        fdt[id].mask   = False
        tdt[id].mask   = False

    ret = dict(tdt=tdt,fdt=fdt,trend=trend,ffit=ffit,p1L=p1L,idL=idL)        
    return ret

def fitcand(t,f,p0,ver=True):
    """
    Fit Candidate Transits

    Starting from the promising (P,epoch,tdur) combinations returned by the
    brute force search, perform a non-linear fit for the transit.

    Parameters
    ----------

    t      : Time series  
    f      : Flux
    p0     : Dictionary {'P':Period,'epoch':Trial epoch,'tdur':Transit Duration}

    """
    twdcad = 2./keptoy.lc
    P = p0['P']
    epoch = p0['epoch']
    tdur = p0['tdur']

    try:
        dLDT = LDT(t,f,p0)
        tdt,fdt,p1L = dLDT['tdt'],dLDT['fdt'],dLDT['p1L']
        nT = len(p1L)
        dtpass = True
    except:
        print sys.exc_info()[1]
        nT = 0 
        dtpass = False
                
    p0 = np.array([P,epoch,0.e-4,tdur])
    fitpass = False
    if (nT >= 3) and dtpass :
        try:
            tfit = tdt.compressed() # Time series to fit 
            ffit = fdt.compressed() # Flux series to fit.

            tbase = t.ptp()
            dp0 =  trsh(P,tbase)
            dp0 = [dp0['dP'],dp0['depoch']]
            p1 , fopt ,iter ,funcalls, warnflag = \
                optimize.fmin(objMT,p0,args=(tfit,ffit,p0,dp0) ,disp=False,full_output=True)

            tfold = tfind.getT(tdt,p1[0],p1[1],p1[3])
            fdt2 = ma.masked_array(fdt,mask=tfold.mask)
            if fdt2.count() > 20:
                s2n = - ma.mean(fdt2)/ma.std(fdt2)*np.sqrt( fdt2.count() )

                fitpass = True
            else: 
                fitpass = False
                s2n = 0
            if ver:
                print "%7.02f %7.02f %7.02f" % (p1[0] , p1[1] , s2n )

        except:
            print sys.exc_info()[1]

    # To combine tables everythin must be a float.
    if fitpass:
        res = dict( P=p1[0],epoch=p1[1],df=p1[2],tdur=p1[3],s2n=s2n )
        return res
    else:
        return dict( P=p0[0],epoch=p0[1],df=p0[2],tdur=p0[3],s2n=0. )

def fitcandW(t,f,dL,view=None,ver=True):
    """
    """
    n = len(dL)
    func = lambda d: fitcand(t,f,d,ver=ver)

    if view != None:
        resL = view.map(func, dL,block=True)
    else:
        resL = map(func, dL)
 
    return resL


def tabval(file,view=None):
    """
    
    """
    tset = atpy.TableSet(file)
    nsim = len(tset.PAR.P)
    tres = tset.RES
    
    # Check the 50 highest s/n peaks in the MF spectrum
    tabval = atpy.TableSet()

    f = keptoy.genEmpLC( qalg.tab2dl(tset.PAR)[0] , tset.LC.t , tset.LC.f)
    t = tset.LC.t


    for isim in range(nsim):
        dL = parGuess(qalg.tab2dl(tres)[isim],nCheck=50)
        resL = fitcandW(tl[isim],fl[isim],dL,view=view)

        print 21*"-" + " %d" % (isim)
        print "   iP      oP      s2n    "
        for d,r in zip(dL,resL):
            print "%7.02f %7.02f %7.02f" % (d['P'],r['P'],r['s2n'])

        tab = qalg.dl2tab(resL)
        tab.table_name = 'SIM%03d' % (isim)
        tabval.append(tab)

    fileL = file.split('.')
    tabval.write(fileL[0]+'_val'+'.fits',overwrite=True)
    return tabval

def parGuess(res,nCheck=50):
    """
    Parameter guess

    Given the results of the matched filter approach, return the guess
    values for the non-linear fitter.

    Parameters
    ----------

    res - Dictionary with the following keys:

        s2n   : Array of s2n
        PG    : Period grid
        epoch : Array of epochs
        twd   : Array of epochs
    
    Optional Parameters
    -------------------

    nCheck : How many s2n points to look at?

    Notes
    -----

    Right now the transit duration is hardwired at 0.3 days.  This it
    should take the output value of the matched filter.

    """

    idCand = np.argsort(-res['s2n'])
    dL = []
    for i in range(nCheck):
        idx = idCand[i]
        d = dict(P=res['PG'][idx],epoch=res['epoch'][idx],
                 tdur=res['twd'][idx]*keptoy.lc)
        dL.append(d)

    return dL


thresh = 0.001


def iPoP(tset,tabval):
    """
    """
    nsim = len(tset.PAR.P)
    print "sim, iP    ,   oP   ,  eP , iepoch,oepoch,eepoch, s2n"
    tres = copy.deepcopy(tset.PAR)
    tres.add_empty_column('oP',np.float)
    tres.add_empty_column('oepoch',np.float)
    tres.add_empty_column('odf',np.float)
    tres.add_empty_column('os2n',np.float)

    tres.add_empty_column('KIC',np.int)

    for isim in range(nsim):
        s2n = ma.masked_invalid(tabval[isim].s2n)
        iMax = s2n.argmax()

        s2n  = tabval[isim].s2n[iMax]
        df  = tabval[isim].df[iMax]

        iP =  tset.PAR.P[isim]
        oP =  tabval[isim].P[iMax]
        
        iepoch = tset.PAR.epoch[isim]
        oepoch = tabval[isim].epoch[iMax]

        if s2n > 5:
            print "%03i %.2f  %.2f  %+.2f  %.2f  %.2f  %+.2f  %.2f" % \
                (isim,iP,oP,100*(iP-oP)/iP, iepoch,oepoch,iepoch-oepoch ,s2n)
        else:
            print "%03i ------  ------  -----  -----  -----  -----  %.2f" % \
                (isim,s2n)

        tres.oP[isim] = oP
        tres.oepoch[isim] = oepoch
        tres.KIC[isim] = tset.LC.keywords['KEPLERID']

        tres.os2n[isim] = s2n
        tres.odf[isim] = df


    return tres

def window(fl,PcadG):
    """
    Compute the window function.

    The fraction of epochs that pass our criteria for transit.
    """

    winL = []
    for Pcad in PcadG:
        flW = tfind.XWrap(fl,Pcad,fill_value=False)
        win = (flW.sum(axis=0) >= 3).astype(float)
        npass = np.where(win)[0].size
        win =  float(npass) / win.size
        winL.append(win)

    return winL

def midTransId(t,p):
    """
    Mid Transit Index

    Return the indecies of mid transit for input parameters.

    Parameters
    ----------

    t - timeseries
    p - dictionary with 'P','epoch','tdur'

    """
    P     = p['P']
    epoch = p['epoch']

    Pcad     = int(round(P/keptoy.lc))
    epochcad = int(round( (epoch-t[0])/keptoy.lc )  )

    nT = t.size/Pcad + 1  # maximum number of transits

    ### Determine the indecies of the points to fit. ###
    ms = np.arange(nT) * Pcad + epochcad
    ms = [m for m in  ms if (m < t.size) & (m > 0) ]
    return ms

def aliasW(t,f,resL0):
    """
    Alias Wrap

    """

    s2n = np.array([ r['s2n'] for r in resL0])
    assert ( s2n > 0).all(),"Cut out failed fits"

    resL = copy.deepcopy(resL0)

    for i in range(len(resL0)):
        X2,X2A,pA,fTransitA,mTransit,mTransitA = alias(t,f,resL0[i])
        if X2A < X2:
            res = fitcand(t,f,pA)
            resL[i] = res

    return resL

def alias(t,f,p):
    """
    Evaluate the Bayes Ratio between signal with P and 2 *P

    Parameters
    ----------

    t : Time series
    f : Flux series
    p : Parameter dictionary.
    
    """

    pA = copy.deepcopy(p)
    pA['P'] = 0.5 * pA['P']
    
    res = LDT(t,f,pA)
    tdt = res['tdt']
    fdt = res['fdt']
    
    pl  = [p['P'],p['epoch'],p['df'],p['tdur']]
    plA = [pA['P'],pA['epoch'],pA['df'],pA['tdur']]

    model  = keptoy.P05(pl  , tdt )
    modelA = keptoy.P05(plA , tdt )

    tTransitA = tfind.getT(tdt.data,pA['P'],pA['epoch'],pA['tdur'])
    
    mTransit  = ma.masked_array(model.data,copy=True,mask=tTransitA.mask)
    mTransitA = ma.masked_array(modelA.data,copy=True,mask=tTransitA.mask)

    fTransitA = ma.masked_array(fdt.data,copy=True,mask=tTransitA.mask)

    X2  = ma.sum( (fTransitA - mTransit)**2 )
    X2A = ma.sum( (fTransitA - mTransitA)**2 )

    print "Input Period Chi2 = %e, Alias Chi2 = %e " % (X2, X2A)

    return X2,X2A,pA,fTransitA,mTransit,mTransitA
    

def getSlice(m,wdcad):
    """
    Get slice
    
    Parameters
    ----------
    m    : middle index (center of the slice).
    wdcad : width of slice list (units of cadence).

    """

    return slice( m-wdcad/2 , m+wdcad/2 )



def tdict(d,prefix=''):
    """
    
    """
    outcol = ['P','epoch','df','tdur']

    incol = [prefix+oc for oc in outcol]

    outd = {}
    for o,c in zip(outcol,incol):
        try:
            outd[o] = d[c]
        except KeyError:
            pass

    return outd









