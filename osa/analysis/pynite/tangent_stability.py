"""Reject postcritical P-Delta equilibria with nonpositive tangent energy."""
import numpy as np
from scipy.linalg import cholesky
from scipy.sparse import diags
from scipy.sparse.linalg import ArpackNoConvergence, eigsh


def tangent_stability(target, reference):
    """Check the symmetric free-DOF tangent, scaled to unit diagonal.

    A converged algebraic solution alone may lie beyond an elastic buckling
    point. Positive tangent energy is a necessary condition for this elastic
    design procedure. This check does not replace member/plate buckling checks.
    """
    from Pynite.Analysis import _partition_D

    free, _restrained, _displacements = _partition_D(target)
    if not free:
        return {'status': 'positive', 'method': 'sem graus de liberdade livres'}
    elastic = target.Ke(reference, check_stability=False, sparse=True).tocsr()
    geometric = target.Kg(reference, sparse=True, first_step=False).tocsr()
    tangent = (elastic+geometric)[free, :][:, free]
    diagonal = tangent.diagonal()
    if not np.all(np.isfinite(tangent.data)) or np.any(diagonal <= 0):
        raise ValueError('Rigidez tangente não positiva na análise P–Delta: equilíbrio elástico instável ou pós-crítico.')
    scaling = diags(1/np.sqrt(diagonal))
    matrix = scaling@((tangent+tangent.T)*.5)@scaling
    try:
        if len(free) <= 500:
            cholesky(matrix.toarray(), lower=True, check_finite=True)
            method = 'Cholesky da rigidez tangente simétrica escalada'
        else:
            value = float(eigsh(matrix, k=1, which='SA', return_eigenvectors=False, tol=1e-7,
                                maxiter=max(1000, 10*len(free)))[0])
            if not np.isfinite(value) or value <= 1e-10:
                raise ValueError('Autovalor tangente não positivo ou numericamente indeterminado.')
            method = 'menor autovalor da rigidez tangente simétrica escalada'
    except (np.linalg.LinAlgError, ArpackNoConvergence, ValueError) as exc:
        raise ValueError('A rigidez tangente P–Delta não comprova equilíbrio elástico estável; reveja a estabilidade do sistema e a proximidade da carga crítica.') from exc
    return {'status': 'positive', 'method': method, 'free_dofs': len(free)}
