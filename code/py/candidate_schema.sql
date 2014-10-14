CREATE TABLE candidate (
  id INTEGER PRIMARY KEY,
  grid_basedir TEXT,
  grid_h5_filename TEXT,
  grid_plot_filename TEXT,
  outfile REAL,
  phot_basedir TEXT,
  phot_fits_filename TEXT,
  phot_plot_filename TEXT,
  s2n REAL,
  s2ncut REAL,
  starname TEXT,
  t0 REAL,
  tdur REAL,
  noise REAL, 
  SES_3 REAL, 
  SES_2 REAL, 
  SES_1 REAL, 
  SES_0 REAL, 
  autor REAL, 
  s2ncut_t0 REAL, 
  SES_even REAL, 
  ph_SE REAL, 
  t0shft_SE REAL, 
  twd INT, 
  SES_odd REAL, 
  P REAL, 
  Pcad REAL, 
  grass REAL,
  s2ncut_mean REAL, 
  num_trans INT,
  mean REAL,
  fit_completed_mcmc int,
  fit_p REAL,
  fit_dt REAL,
  fit_b REAL,
  fit_tau REAL
);