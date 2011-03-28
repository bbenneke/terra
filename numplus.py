"""
Functions to supplement numpy.
"""

import numpy as np

def binavg(x,y,bins):
    """
    Computes the average value of y on a bin by bin basis.

    x - array of x values
    y - array 
    bins - array of bins in x

    x = array([1,2,3,4])
    y = array([1,3,2,4])
    bins = array([0,2.5,5])
    
    returns
    
    array([1.25,3.75]),array([2.,3.])

    Notes:

    Benchmarked this over a similar fucntion that loops over where statements
    While the performance is comparable for nbins ~ 10, as one goes to higher
    number of bins, doing the sorting outside the loop makes a *huge* difference
    """

    #make the arrays monotonically increasing in x
    sarg = np.argsort(x)
    x = x[sarg]
    y = y[sarg]

    # for each point compute the index of the bin that it falls into.
    idx = np.digitize(x,bins) 

    # compute the midpoint of each bin.
    binx = bins[:-1] + (bins[1:]-bins[:-1])/2
    nbin = len(binx)
    biny = np.empty(nbin,dtype=y.dtype)

    #number of points in each bin
    nidx = np.bincount(idx)[1:]

    lslice = 0 # the left most slice
    for i in range(nbin):
        # Compute the average value in each bin
        rslice = lslice + nidx[i]
        biny[i] = np.mean(y[lslice:rslice]) 
        lslice += nidx[i] # move left slice up

    return binx,biny

