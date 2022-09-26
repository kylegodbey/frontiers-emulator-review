# Try to write clean tests following BDD and Gherkin keywords:
# https://cucumber.io/docs/gherkin/reference/

# from re import I
import pytest

import numpy as np
from scipy import stats
from scipy.special import spherical_jn

from emulate import CompoundMesh
from emulate import fourier_transform_partial_wave
from emulate import gaussian_radial_fourier_transform
from emulate.utils import (
    yamaguchi_form_factor_momentum_space,
    yamaguchi_form_factor_position_space,
    yamaguchi_radial_wave_function,
    yamaguchi_scattering_amplitude,
    schrodinger_residual,
)
from emulate import NewtonEmulator, BoundaryCondition, KohnLippmannSchwingerEmulator


def test_fourier_transform():
    mesh = CompoundMesh([0, 0.1, 5, 10], [50, 50, 50, 50])
    r, dr = mesh.x, mesh.w
    a = 0.7
    k_grid = np.linspace(0, 10, 101)
    ell = 0

    f_r = np.exp(-a * r**2)
    f_k = fourier_transform_partial_wave(f=f_r, r=r, dr=dr, k=k_grid, ell=ell)
    f_k_exact = gaussian_radial_fourier_transform(x=k_grid, a=a)

    np.testing.assert_allclose(actual=f_k, desired=f_k_exact, atol=1e-10, rtol=1e-1)


def test_reverse_fourier_transform():
    mesh = CompoundMesh([0, 0.1, 5, 10], [50, 50, 50, 50])
    k, dk = mesh.x, mesh.w
    a = 0.7
    r_grid = np.linspace(0, 10, 101)
    ell = 0

    f_r = np.exp(-a * r_grid**2)
    f_k = gaussian_radial_fourier_transform(x=k, a=a)
    f_r_reverse = fourier_transform_partial_wave(f=f_k, r=k, dr=dk, k=r_grid, ell=ell)

    np.testing.assert_allclose(actual=f_r_reverse, desired=f_r, atol=1e-10, rtol=1e-1)


def test_yamaguchi_position_form_factor():
    mesh = CompoundMesh([0, 0.1, 5, 10], [50, 50, 50, 50])
    k, dk = mesh.x, mesh.w
    r, dr = mesh.x, mesh.w
    beta = 1
    # ell must be >= 2 else the numerical Fourier transform is too noisy.
    # Assume since it works for >=2 then the analytic form works for < 2 as well.
    ell = 2

    # The momentum space is simple. Compute it exactly.
    f_k = yamaguchi_form_factor_momentum_space(k=k, beta=beta, ell=ell)
    # Compute its fourier transform numerically with a trusted function
    f_r_numeric = fourier_transform_partial_wave(f=f_k, r=k, dr=dk, k=r, ell=ell)

    # Ensure our analytic form matches the numeric one
    f_r = yamaguchi_form_factor_position_space(r=r, beta=beta, ell=ell)

    np.testing.assert_allclose(actual=f_r, desired=f_r_numeric, atol=1e-10, rtol=1e3)


def test_yamaguchi_scattering_amplitude():
    # Rule: The analytic Yamaguchi scattering amplitude should match the empirical version from the LS equation

    # Given a quadrature mesh and other parameters
    mesh = CompoundMesh([0, 0.1, 5, 10], [50, 50, 50, 50])
    k, dk = mesh.x, mesh.w
    beta = 2.0
    q_cm = np.array([0.1, 1, 2])
    strength = np.array([3])

    # And a Yamaguchi potential
    f_k = yamaguchi_form_factor_momentum_space(k=k, beta=beta, ell=0)
    V1 = (f_k[:, None] * f_k)[..., None]

    # When an empirical on-shell K matrix is computed
    newton = NewtonEmulator(
        V0=np.zeros_like(V1[..., 0]),
        V1=V1,
        k=k,
        dk=dk,
        q_cm=q_cm,
        boundary_condition=BoundaryCondition.STANDING,
        nugget=1e-10,
    )
    K_ls = newton.predict(strength, full_space=True)

    # And the analytic Yamaguchi K matrix is evaluated
    K_analytic = yamaguchi_scattering_amplitude(
        q_cm=q_cm, beta=beta, strength=strength, include_q=True
    )

    # Then these two approaches should match
    np.testing.assert_allclose(actual=K_analytic, desired=K_ls, atol=1e-10, rtol=1e-1)


@pytest.mark.parametrize("ell", [0, 1, 2, 3])
def test_free_wave_function(ell):
    # Rule: The free wave function should satisfy the Schrodinger equation

    # Given a free wave function on a quadrature mesh in position space
    # And a choice of angular momentum, ell
    n_intervals = 21
    mesh = CompoundMesh(
        np.linspace(0, 10, n_intervals), 100 * np.ones(n_intervals - 1, dtype=int)
    )
    r, dr = mesh.x, mesh.w
    n_r = len(r)
    q_cm = np.array([0.1, 1, 2])
    j_ell = spherical_jn(ell, r * q_cm[:, None])

    # When it is inserted in the Schrodinger equation with no external potential
    V = np.zeros((n_r, n_r))
    residual = schrodinger_residual(
        psi=j_ell, V=V, r=r, dr=dr, q_cm=q_cm[:, None], ell=ell
    )
    # And endpoint effects are removed (due to numerical gradients)
    residual = residual[..., 2:-2]

    # Then the residual should be almost zero
    np.testing.assert_allclose(
        actual=residual, desired=np.zeros_like(residual), atol=1e-2, rtol=1
    )


@pytest.mark.parametrize("ell", [0])
def test_yamaguchi_wave_function(ell):
    # Rule: The Yamaguchi wave function should satisfy the Schrodinger equation

    # Given a Yamaguchi wave function on a quadrature mesh in position space
    # And a choice of angular momentum, ell
    n_intervals = 21
    mesh = CompoundMesh(
        np.linspace(0, 10, n_intervals), 100 * np.ones(n_intervals - 1, dtype=int)
    )
    r, dr = mesh.x, mesh.w
    # n_r = len(r)
    q_cm = np.array([0.1, 1, 2])
    beta = 0.5
    strength = 5

    psi_ell = yamaguchi_radial_wave_function(
        r=r, q_cm=q_cm[:, None], beta=beta, strength=strength
    )

    # When it is inserted in the Schrodinger equation with a non-local Yamaguchi external potential
    f_r = yamaguchi_form_factor_position_space(r=r, beta=beta, ell=ell)
    V_r = f_r[:, None] * f_r * strength
    residual = schrodinger_residual(
        psi=psi_ell, V=V_r, r=r, dr=dr, q_cm=q_cm[:, None], ell=ell
    )
    # And endpoint effects are removed (due to numerical gradients)
    residual = residual[..., 2:-2]

    # Then the residual should be almost zero
    np.testing.assert_allclose(
        actual=residual, desired=np.zeros_like(residual), atol=1e-2, rtol=1
    )


def test_wave_function_from_reactance_matrix():
    # Rule: The analytic Yamaguchi scattering amplitude should match the empirical version from the LS equation

    # Given a quadrature mesh
    n_intervals = 21
    nodes = np.linspace(0, 10, n_intervals)
    n_points = 100 * np.ones(n_intervals - 1, dtype=int)
    mesh = CompoundMesh(nodes, n_points)
    k, dk = mesh.x, mesh.w
    r, dr = mesh.x, mesh.w

    # And other parameters
    beta = 2.0
    ell = 0
    q_cm = np.array([0.1, 1, 2])
    strength = np.array([3])
    hbarsq_over_M = 1

    # And a Yamaguchi potential
    f_k = yamaguchi_form_factor_momentum_space(k=k, beta=beta, ell=ell)
    f_r = yamaguchi_form_factor_position_space(r=r, beta=beta, ell=ell)
    V1_k = (f_k[:, None] * f_k)[..., None] * strength
    V1_r = (f_r[:, None] * f_r)[..., None] * strength

    # When the Lippmann Schwinger equation is evaluated to solve for the reactance matrix, K
    newton = NewtonEmulator(
        V0=np.zeros_like(V1_k[..., 0]),
        V1=V1_k,
        k=k,
        dk=dk,
        q_cm=q_cm,
        boundary_condition=BoundaryCondition.STANDING,
        nugget=1e-10,
    )

    schwing = KohnLippmannSchwingerEmulator(
        V0=np.zeros_like(V1_r[..., 0]),
        V1=V1_r,
        r=r,
        dr=dr,
        NVP=newton,
        inv_mass=hbarsq_over_M,
        ell=ell,
    )

    # And the K matrix from the LS equation is converted to a wave function in position space
    params = np.array([1])
    psi_schwing = schwing.predict(params, full_space=True).T

    # And the analytic Yamaguchi wave function is evaluated
    psi_analytic = yamaguchi_radial_wave_function(
        r=r, q_cm=q_cm[:, None], beta=beta, strength=strength
    )

    # Then the wave function from the LS equation and the analytic version should match
    np.testing.assert_allclose(
        actual=psi_schwing, desired=psi_analytic, atol=1e-5, rtol=1e-1
    )


def test_quadrature_infinite():
    mesh = CompoundMesh([0, 2], [50, 50])
    x, dx = mesh.x, mesh.w

    sigma = 5
    half_gaussian = stats.halfnorm(loc=0, scale=sigma).pdf(x)

    numerical_integral = np.sum(half_gaussian * dx)
    np.testing.assert_allclose(numerical_integral, 1.0)


def test_quadrature_finite():
    mesh = CompoundMesh([-1, 1], [50])
    x, dx = mesh.x, mesh.w

    numerical_integral = np.sum(x**2 * dx)
    np.testing.assert_allclose(numerical_integral, 2 / 3)


def test_quadrature_finite2():
    mesh = CompoundMesh([-1, 0, 1], [50, 50])
    x, dx = mesh.x, mesh.w

    numerical_integral = np.sum(x**2 * dx)
    np.testing.assert_allclose(numerical_integral, 2 / 3)
