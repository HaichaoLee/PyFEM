# -*- coding: utf-8 -*-
"""
Created on Tue Nov 14 15:57:29 2017

@author: haiau
"""

import math
import numpy as np
import pylab as pl
import AxisymmetricElement as AE
import QuadElement as QE
import FEMNode as FN
import FEMMesh as FM
import FEMOutput as FO
import Material as mat
import NewmarkAlgorithm as NM
import Solver as sv
import IntegrationData as idat
import MeshGenerator as mg
import cProfile
import pstats
        
class LinearMagneticMaterial(mat.Material):
    def __init__(self, mur, epsr, sigma, idx):
        self.mu0 = mur*4.0e-7*np.pi
        self.sigma = sigma
        self.eps = epsr*8.854187817e-12
        self.dM = np.zeros(2)
        self.idx = idx
        self.Mu = np.zeros(2)
        self.hysteresis = False
        
    def getID(self):
        return self.idx

class JAMaterial(mat.Material):
    def __init__(self, sigma, ng, idx):
        self.a = 0.0
        self.alpha = 0.0
        self.c = 0.0
        self.Ms = 0.0
        self.k = 0.0
        self.delta = 1
        self.sigma = sigma
        self.eps = 8.854187817e-12
        self.dM = np.zeros(2)
        self.mu0 = 4.0e-7*np.pi
        self.ng = ng
        self.Bprev = np.zeros((2,ng))
        self.Mprev = np.zeros((2,ng))
        self.dMprev = np.zeros((2,ng))
        self.Hprev = np.zeros((2,ng))
        self.idx = idx
        self.Mu = np.zeros(2)
        self.Ndof = 1
        self.hystereis = True
        
    def getID(self):
        return self.idx
        
    def updateParamters(self, a, alpha, c, Ms, k):
        self.a = a
        self.alpha = alpha
        self.c = c
        self.Ms = Ms
        self.k = k
        
    def calculateParameters(self, temperature):
        t0 = temperature/1.0213513430455913e3
        self.Ms = 1.6666270496980909e6*math.pow((1.0-t0),2.0588027319169142e-1)
        self.a = math.exp(1.1065973379588542e1)*\
        math.pow((1-t0),1.7544087504777564e-1)
        self.alpha=math.exp(-2.7711734827753376e0)*\
        math.pow((1-t0),-1.1702805122223958e-1)
        self.c = math.exp(-1.339064360358903e0)*\
        math.pow((1-t0),-3.4877155040447291e-2)
        self.k = math.exp(8.8017026926921e0)*\
        math.pow((1-t0),2.4926461785971135e-1)
        
    def calculateOne(self,data,b,ix):
        if self.Ndof > 1:
            T = data.getU()[1]
        else:
            T = 298.0
        self.calculateParameters(T)
        if T>=1.02407149938785e3:
            self.Mu[ix,data.ig] = 0.0
            self.dM[ix,data.ig] = 0.0
            return
            
        nstep = 400
        try:
            Bprev = self.Bprev[ix,data.ig]
        except IndexError:
            print(ix,data.ig)
        Hprev = self.Hprev[ix,data.ig]
        Mprev = self.Mprev[ix,data.ig]
        if(b < Bprev):
            self.delta = -1
        else:
            self.delta = 1
            
        deltab = (b - Bprev)/nstep
        barr = Bprev
        h = Hprev
        mu1 = Mprev
        
        if math.fabs(deltab) > 0:
            for i in range(nstep):
                he = h + self.alpha*mu1
                man = self.Ms*Langevin(he/self.a)
                dman = self.Ms/self.a*dLangevin(he/self.a)
                dman = dman/(1-self.alpha*dman)
                c1 = 1.0/(1.0+self.c)
                dmu1 = c1*(man-mu1)/(self.delta*self.k-\
                self.alpha*(man-mu1)+self.c*c1*dman)
                if dmu1 <0:
                    dmu1 = -dmu1
                dmu1 = dmu1/(self.mu0*(1.0+dmu1))
                mu1 = mu1 + dmu1*deltab
                
                barr = barr + deltab
                h = barr/self.mu0 - mu1
                self.Mu[ix] = mu1
                self.dM[ix] = dmu1
        else:
            self.Mu[ix] = Mprev
            self.dM[ix] = self.dMprev[ix,data.ig]
        if data.store:
            self.Bprev[ix,data.ig] = b
            self.Hprev[ix,data.ig] = h
            self.Mprev[ix,data.ig] = self.Mu[ix]
            self.dMprev[ix,data.ig] = self.dM[ix]
            
    def calculate(self,data):
        B = data.getB()
        self.calculateOne(data,B[0],0)
        self.calculateOne(data,B[1],1)
        
def Langevin(x):
    n = 8
    if math.fabs(x)>1.0:
        return 1.0e0/math.tanh(x) - 1.0e0/x
    else:
        g = 0.0
        for k in range(n,1,-1):
            bk = 2.0*k + 1.0
            g = x*x/(bk + g)
        return x/(3.0 + g)
        
def dLangevin(x):
    if math.fabs(x) < 1.0e-5:
        return 1.0e0/3.0e0
    else:
        a = math.sinh(x)
        return 1.0/(x*x)-1.0/(a*a)
    
class AxiSymMagnetic(AE.AxisymmetricQuadElement):
    def __init__(self, Nodes, pd, basisFunction, nodeOrder,material, intData):
        AE.AxisymmetricQuadElement.__init__(self,Nodes,pd,basisFunction,\
        nodeOrder,material,intData)
        self.store = True
    
    def getB(self):
        B = np.array([-self.gradu_[1,0],self.gradu_[0,0]+self.u_[0]/self.x_[0]])
        return B
        
    def updateMat(self, material):
        self.material = material
    
    def calculateKLinear(self, K, inod, jnod, t):
        """
        Calculate Stiffness matrix K
        """

        r = self.x_[0]
        K[0,0] = self.dN_[0,inod]*self.dN_[0,jnod]
        K[0,0] += self.N_[inod]*self.dN_[0,jnod]/r
        K[0,0] += self.dN_[0,inod]*self.N_[jnod]/r
        K[0,0] += self.N_[inod]*self.N_[jnod]/(r*r)
        K[0,0] += self.dN_[1,inod]*self.dN_[1,jnod]
        K[0,0] /= self.material.mu0
        # magnetization
        if self.material.hysteresis:
            dm1 = self.material.dM[0]
            dm2 = self.material.dM[1]
            K[0,0] -= dm2*self.dN_[0,inod]*self.dN_[0,jnod]
            K[0,0] -= dm2*self.N_[inod]*self.dN_[0,jnod]/r
            K[0,0] -= dm2*self.dN_[0,inod]*self.N_[jnod]/r
            K[0,0] -= dm2*self.N_[inod]*self.N_[jnod]/(r*r)
            K[0,0] -= dm1*self.dN_[1,inod]*self.dN_[1,jnod]
        K[0,0] *= self.getFactor()
    
    def calculateDLinear(self, D, inod, jnod, t):
        """
        Calculate Damping matrix D
        """
        D[0,0] = self.N_[inod]*self.N_[jnod]
        D *= self.material.sigma*self.getFactor()
    
    def calculateMLinear(self, M, inod, jnod, t):
        """
        Calculate Mass matrix M
        """
        M[0,0] = self.N_[inod]*self.N_[jnod]
        M *= self.material.eps*self.getFactor()
    
    def calculateR(self, R, inod, t):
        """
        Calculate load matrix R
        """
        r = self.x_[0]
        R[0] = self.dN_[1,inod]*self.gradu_[1,0]
        R[0] += (self.N_[inod]/r+self.dN_[0,inod])*\
        (self.u_[0]/r+self.gradu_[0,0])
        R[0] /= self.material.mu0
        if self.material.hysteresis:
            R[0] += self.material.Mu[0]*self.dN_[1,inod]
            R[0] -= self.material.Mu[1]*(self.N_[inod]/r+self.dN_[0,inod])
        if self.timeOrder > 0:
            R[0] += self.N_[inod]*self.v_[0]*self.material.sigma
        if self.timeOrder == 2:
            R[0] += self.N_[inod]*self.a_[0]*self.material.eps
        R[0] -= self.N_[inod]*self.getBodyLoad(t)
        R[0] *= self.getFactor()

def readInput(filename,nodeOrder,timeOrder,intData,Ndof = 1):
    mesh = FM.Mesh()
    file = open(filename,'r')
    int(file.readline().split()[1])
    nnode = int(file.readline().split()[1])
    nnod = int(file.readline().split()[1])
    nelm = int(file.readline().split()[1])
    int(file.readline().split()[1])
    int(file.readline().split()[1])
    file.readline()
    for i in range(nnod):
        a = list(float(x) for x in file.readline().split())
        x_ = np.array(a[1:3])
        mesh.addNode(FN.Node(x_,Ndof,timeOrder,i))
    file.readline()
    for i in range(nelm):
        a = list(int(x) for x in file.readline().split())
        nodes = []
        for j in range(nnode):
            nodes.append(findNode(mesh.getNodes(),a[j+1]-1))
        e = AxiSymMagnetic(nodes,[2,2],\
        QE.LagrangeBasis1D,nodeOrder,None,intData)
        mesh.addElement(e)
    file.readline()
    for i in range(nnod):
        a = list(float(x) for x in file.readline().split())
        for j in range(Ndof):
            mesh.getNodes()[i].setLoad(a[j+1],j)
            
    file.readline()
    for i in range(nnod):
        a = file.readline().split()
        for j in range(Ndof):
            mesh.getNodes()[i].setConstraint(int(a[2*j+1+2])==0,float(a[2*(j+1)+2]),j)
            
    air = LinearMagneticMaterial(1.0,1.0,0.0,2)
    cooper = LinearMagneticMaterial(1.0,1.0,5.0e6,3)
    steel = LinearMagneticMaterial(100.0,1.0,5.0e6,1)
    file.readline()
    for i in range(nelm):
        a = list(int(x) for x in file.readline().split())
        if a[1] == 2:
            mesh.getElements()[i].updateMat(air)
        if a[1] == 3:
            mesh.getElements()[i].updateMat(cooper)
        if a[1] == 1:
            mesh.getElements()[i].updateMat(steel)
            #mesh.getElements()[i].updateMat(JAMaterial(5.0e6,intData.getNumberPoint(),1))
    file.close()
    return mesh
    
        
        
def findNode(nodes,id_number):
    for node in nodes:
        if node.get_id_number() == id_number:
            return node
    raise Exception()

Ndof = 1             
tOrder = 2
Ng = [3,3]
totalTime = 1.0e-5
numberTimeSteps = 10
rho_inf = 0.9
tol = 1.0e-8
load = 355.0/0.015/0.01

intDat = idat.GaussianQuadrature(Ng, 2, idat.Gaussian1D)

#nodeOrder = [[2,1,0,2,1,0,2,1,0],
#             [2,2,2,1,1,1,0,0,0]]
#
#mesh = readInput('/home/haiau/Documents/testfortran_.dat',nodeOrder,tOrder,intDat)
#for e in mesh.getElements():
#    if e.material.getID() == 3:
#        def loadfunc(x,t):
#                return load*math.cos(8.1e3*2*np.pi*t)
#        e.setBodyLoad(loadfunc)

def create_mesh():
    nodes = []
    nodes.append(FN.Node([0.0,-0.2],Ndof,timeOrder = tOrder))
    nodes.append(FN.Node([0.015,-0.2],Ndof,timeOrder = tOrder))
    nodes.append(FN.Node([0.0225,-0.2],Ndof,timeOrder = tOrder))
    nodes.append(FN.Node([0.0325,-0.2],Ndof,timeOrder = tOrder))
    nodes.append(FN.Node([0.2,-0.2],Ndof,timeOrder = tOrder))
    
    edges = [mg.Edge(nodes[i],nodes[i+1]) for i in range(len(nodes)-1)]
    
    geo = mg.Geometry()
    d = np.array([0.0,1.0])
    s = [0.1,0.064,0.015,0.0135,0.015,0.0135,0.015,0.064,0.1]
    for e in edges:
        geo.addPolygons(e.extendToQuad(d,s))
    
    polys = geo.getPolygons()
    for i in range(9):
        polys[i].setDivisionEdge13(8)
        
    for i in range(9,18):
        polys[i].setDivisionEdge13(2)
        
    for i in range(27,36):
        polys[i].setDivisionEdge13(5)
        
    for i in range(0,28,9):
        polys[i].setDivisionEdge24(4)
        
    for i in range(8,36,9):
        polys[i].setDivisionEdge24(4)
        
    for i in range(1,29,9):
        polys[i].setDivisionEdge24(2)
        
    for i in range(7,35,9):
        polys[i].setDivisionEdge24(4)
        
    mat2 = LinearMagneticMaterial(1.0,0.0,0.0,2)
    mat3 = LinearMagneticMaterial(1.0,0.0,0.0,3)
    #mat1 = JAMaterial(5.0e6,9,1)
    mat1 = LinearMagneticMaterial(100.0,1.0,0.0,1)
    for i in range(1,8):
        polys[i].setMaterial(mat1)
        
    polys[20].setMaterial(mat2)
    polys[20].setBodyLoad(load)
    polys[22].setMaterial(mat2)
    polys[22].setBodyLoad(load)
    polys[24].setMaterial(mat2)
    polys[24].setBodyLoad(load)
    
    for poly in polys:
        if poly.getMaterial() is None:
            poly.setMaterial(mat3)
        
    geo.mesh()
    
    [nodesx, elems, mats, bdls] = geo.getMesh(None,mg.nodesQuad9,2)
        
    #fig = geo.plot(poly_number = True, fill_mat = True)
        
    #geo.plotMesh(col = 'b-',fill_mat = True)
    #for i,node in enumerate(nodesx):
    #    #pl.plot(node.getX()[0],node.getX()[1],'.b')
    #    if math.fabs(node.getX()[0] - 0.0)<1.0e-14:
    #        pl.text(node.getX()[0],node.getX()[1],str(i))
       
    for n in nodesx:
        if math.fabs(n.getX()[0]-0.0)<1.0e-14 or \
        math.fabs(n.getX()[1]+0.2)<1.0e-14 or \
        math.fabs(n.getX()[0]-0.2)<1.0e-14 or \
        math.fabs(n.getX()[1]-0.2)<1.0e-14:
            n.setConstraint(False, 0.0, 0)
            #n.setConstraint(False, 0.0, 1)
            #pl.plot(n.getX()[0],n.getX()[1],'.r')
    
    elements = []
    for i,e in enumerate(elems):
        #if mats[i] is JAMaterial:
        #    m = JAMaterial(5.0e6,9,1)
        #else:
        #    m = mats[i]
        m = mats[i]
        elements.append(AxiSymMagnetic(e,[2,2],QE.LagrangeBasis1D,\
        QE.generateQuadNodeOrder([2,2],2),m,intDat))
        if bdls[i] is not None:
            def loadfunc(x,t):
                return load*math.cos(8.1e3*2*np.pi*t)
                #return load
        else:
            loadfunc = None
        elements[i].setBodyLoad(loadfunc)
        
    mesh =  FM.Mesh()
    mesh.addNodes(nodesx)
    mesh.addElements(elements)
        
    return mesh

def create_simple_mesh():
    nodes = []
    nodes.append(FN.Node([0.0,0.0],Ndof,timeOrder = tOrder))
    nodes.append(FN.Node([1.0,0.0],Ndof,timeOrder = tOrder))
    
    edge = mg.Edge(nodes[0],nodes[1])
    poly = edge.extendToQuad(np.array([0.0,1.0]),1.0)
    
    geo = mg.Geometry()
    geo.addPolygon(poly)
    
    mat2 = LinearMagneticMaterial(1.0,0.0,0.0,2)
    poly.setMaterial(mat2)
    
    geo.mesh()
    [nodesx, elems, mats, bdls] = geo.getMesh(None,mg.nodesQuad9,2)
    for n in nodesx:
        if math.fabs(n.getX()[0]-0.0)<1.0e-14:
            n.setConstraint(False, 0.0, 0)
    elements = []
    for i,e in enumerate(elems):
        m = mats[i]
        elements.append(AxiSymMagnetic(e,[2,2],QE.LagrangeBasis1D,\
        QE.generateQuadNodeOrder([2,2],2),m,intDat))
        
    mesh =  FM.Mesh()
    mesh.addNodes(nodesx)
    mesh.addElements(elements)
    
    def loadfunc(t):
        #return load*math.cos(8.1e3*2*np.pi*t)
        return load*math.cos(8.1e3*2*np.pi*t)
    
    mesh.Nodes[4].setLoad(loadfunc,0)
    
    return mesh
        
mesh = create_simple_mesh()

mesh = create_mesh()

mesh.generateID()      

output = FO.StandardFileOutput('/home/haiau/Documents/result.dat')
alg = NM.NonlinearNewmarkAlgorithm(mesh,tOrder,output,sv.numpySolver(),\
totalTime, numberTimeSteps,rho_inf,tol=1.0e-8)

#alg.calculate()

cProfile.run('alg.calculate()','calculate.profile')
stats = pstats.Stats('calculate.profile')
stats.strip_dirs().sort_stats('time').print_stats()

