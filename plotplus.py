"""
Functions that supplement matplotlib.
"""


import numpy as np
import matplotlib.pyplot as plt

def appendAxes(axlist,nplots,plotidx):
    """
    Append axes to a list
    axlist  - list of axis objects
    nplots  - total number of plots
    plotidx - which plot are we on?
    """
    axlist.append( plt.subplot(nplots,1,plotidx+1) )

    return axlist

def mergeAxes(figure):
    """
    A simple function which merges the x-axes of a figure.  Similar to
    the ``MULTIPLOT`` function in IDL.
    """
    figure.subplots_adjust(hspace=0.0001)
    axlist = figure.get_axes()
    nax = len(axlist)

    lim = (0,0)
    for i in np.arange(nax):
        curlim = axlist[i].get_xlim()
        lim = min(lim[0],curlim[0]),max(lim[1],curlim[1])

        ylim = axlist[i].get_ylim()
        yticks = axlist[i].get_yticks() 
        dtick = yticks[1] - yticks[0]
        newyticks = np.linspace(ylim[0],ylim[1],(ylim[1]-ylim[0])/dtick+1)

        # Special treatment for last axis
        if i != nax-1 :
            axlist[i].set_xticklabels('',visible=False)
            axlist[i].set_yticks(newyticks[1:])
            axlist[i].set_xlabel('')

            # Don't plot duplicate y axes
            if axlist[i].get_ylabel() == axlist[nax-1].get_ylabel():
                axlist[i].set_ylabel('')

    for ax in axlist:
        ax.set_xlim(lim)

    return figure

def mergeAxesTest():
    """
    A test to see if mergeAxes is working.
    """

    x = np.linspace(0,10,100)
    y = np.sin(x)

    f = plt.figure()
    ax = []
    nplots = 3
    for i in np.arange(nplots):
        ax.append( plt.subplot(nplots,1,i+1) )
        ax[i].scatter(x,y)
        ax[i].set_xlabel('test')
        ax[i].set_ylabel('test y')

    f = mergeAxes(f)
    plt.show()
    return f

def errpt(ax,coord,xerr=None,yerr=None,**kwargs):
    """
    Overplot representitive error bar on an axis.

    ax    - axis object to manipulate and return
    coord - the coordinates of error point (in device coordinates)
            [0.1,0.1] is lower left
    xerr/yerr  : [ scalar | 2x1 array-like ] 
    """
    inv = ax.transData.inverted()
    pt = inv.transform( ax.transAxes.transform( coord ) )
    ax.errorbar(pt[0],pt[1],xerr=xerr,yerr=yerr,elinewidth=2,capsize=0,**kwargs)
    return ax

def errptTest(**kwargs):
    """
    Quick test to see if errptTest is working
    """

    ax = plt.subplot(111)
    xerr = yerr = np.array([[.1],[.2]])
    ax = errpt(ax,(.2,.2),xerr=xerr,yerr=yerr,**kwargs)
