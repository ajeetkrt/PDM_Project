--
-- PostgreSQL database dump
--

\restrict XiJJPmhdJrleGaLrr01KMnaKud7hcq9reFosW2sTvkXmwfb1GNx7BDV7Q11SO3A

-- Dumped from database version 17.11
-- Dumped by pg_dump version 17.11

SET statement_timeout = 0;
SET lock_timeout = 0;
SET idle_in_transaction_session_timeout = 0;
SET transaction_timeout = 0;
SET client_encoding = 'UTF8';
SET standard_conforming_strings = on;
SELECT pg_catalog.set_config('search_path', '', false);
SET check_function_bodies = false;
SET xmloption = content;
SET client_min_messages = warning;
SET row_security = off;

SET default_tablespace = '';

SET default_table_access_method = heap;

--
-- Name: bank_master; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.bank_master (
    id integer NOT NULL,
    bank_name character varying(80) NOT NULL,
    isactive boolean DEFAULT true NOT NULL
);


ALTER TABLE public.bank_master OWNER TO postgres;

--
-- Name: bank_master_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.bank_master_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.bank_master_id_seq OWNER TO postgres;

--
-- Name: bank_master_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.bank_master_id_seq OWNED BY public.bank_master.id;


--
-- Name: drivers; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.drivers (
    id integer NOT NULL,
    userid integer NOT NULL,
    usertypeid integer,
    aadharno character varying(12) NOT NULL,
    license_no character varying(30) NOT NULL,
    vehicle_no character varying(25),
    alt_phone character varying(10),
    address text,
    dlimage character varying(255),
    aadharimage character varying(255),
    driverimage character varying(255),
    joiningdate date,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.drivers OWNER TO postgres;

--
-- Name: drivers_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.drivers_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.drivers_id_seq OWNER TO postgres;

--
-- Name: drivers_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.drivers_id_seq OWNED BY public.drivers.id;


--
-- Name: finance_entries; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.finance_entries (
    id integer NOT NULL,
    amount numeric(12,2) NOT NULL,
    bank_name character varying(80) NOT NULL,
    user_id integer,
    remarks text,
    entry_date date DEFAULT CURRENT_DATE NOT NULL,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    type_id integer,
    fd_no character varying(40),
    CONSTRAINT finance_entries_amount_check CHECK ((amount > (0)::numeric))
);


ALTER TABLE public.finance_entries OWNER TO postgres;

--
-- Name: finance_entries_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.finance_entries_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.finance_entries_id_seq OWNER TO postgres;

--
-- Name: finance_entries_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.finance_entries_id_seq OWNED BY public.finance_entries.id;


--
-- Name: finance_type_master; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.finance_type_master (
    id integer NOT NULL,
    type_name character varying(50) NOT NULL,
    isactive boolean DEFAULT true NOT NULL
);


ALTER TABLE public.finance_type_master OWNER TO postgres;

--
-- Name: finance_type_master_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.finance_type_master_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.finance_type_master_id_seq OWNER TO postgres;

--
-- Name: finance_type_master_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.finance_type_master_id_seq OWNED BY public.finance_type_master.id;


--
-- Name: rentaldetails; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.rentaldetails (
    id integer NOT NULL,
    userid integer NOT NULL,
    usertypeid integer,
    aadharno character varying(12) NOT NULL,
    rentagrement character varying(255),
    panno character varying(10),
    aadharimage character varying(255),
    panimage character varying(255),
    floortype character varying(50),
    aadhar_address text,
    occupation character varying(100),
    total_member integer DEFAULT 1 NOT NULL,
    rentalimage character varying(255),
    rental_joiningdate date,
    created_at timestamp without time zone DEFAULT now() NOT NULL
);


ALTER TABLE public.rentaldetails OWNER TO postgres;

--
-- Name: rentaldetails_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.rentaldetails_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.rentaldetails_id_seq OWNER TO postgres;

--
-- Name: rentaldetails_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.rentaldetails_id_seq OWNED BY public.rentaldetails.id;


--
-- Name: rentdetails; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.rentdetails (
    id integer NOT NULL,
    year integer NOT NULL,
    rentamount numeric(12,2) NOT NULL,
    currentdate timestamp without time zone DEFAULT now() NOT NULL,
    rentalid integer NOT NULL,
    month smallint DEFAULT EXTRACT(month FROM CURRENT_DATE) NOT NULL,
    last_updated_at timestamp without time zone,
    last_update_note text
);


ALTER TABLE public.rentdetails OWNER TO postgres;

--
-- Name: rentdetails_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.rentdetails_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.rentdetails_id_seq OWNER TO postgres;

--
-- Name: rentdetails_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.rentdetails_id_seq OWNED BY public.rentdetails.id;


--
-- Name: ride_finance_entries; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.ride_finance_entries (
    id integer NOT NULL,
    type_id integer,
    amount numeric(12,2) NOT NULL,
    bank_name character varying(80) NOT NULL,
    fd_no character varying(40),
    user_id integer,
    remarks text,
    entry_date date DEFAULT CURRENT_DATE NOT NULL,
    created_at timestamp without time zone DEFAULT now(),
    updated_at timestamp without time zone,
    CONSTRAINT ride_finance_entries_amount_check CHECK ((amount > (0)::numeric))
);


ALTER TABLE public.ride_finance_entries OWNER TO postgres;

--
-- Name: ride_finance_entries_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.ride_finance_entries_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.ride_finance_entries_id_seq OWNER TO postgres;

--
-- Name: ride_finance_entries_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.ride_finance_entries_id_seq OWNED BY public.ride_finance_entries.id;


--
-- Name: ridedetails; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.ridedetails (
    id integer NOT NULL,
    driverid integer NOT NULL,
    ride_date date DEFAULT CURRENT_DATE NOT NULL,
    km_driven numeric(9,1) NOT NULL,
    meter_start numeric(10,1),
    meter_end numeric(10,1),
    meter_image character varying(255),
    amount numeric(12,2) DEFAULT 0 NOT NULL,
    remarks text,
    currentdate timestamp without time zone DEFAULT now() NOT NULL,
    CONSTRAINT ridedetails_amount_check CHECK ((amount >= (0)::numeric)),
    CONSTRAINT ridedetails_km_driven_check CHECK ((km_driven >= (0)::numeric))
);


ALTER TABLE public.ridedetails OWNER TO postgres;

--
-- Name: ridedetails_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.ridedetails_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.ridedetails_id_seq OWNER TO postgres;

--
-- Name: ridedetails_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.ridedetails_id_seq OWNED BY public.ridedetails.id;


--
-- Name: users; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.users (
    id integer NOT NULL,
    firstname character varying(100) NOT NULL,
    lastname character varying(100) NOT NULL,
    email character varying(255) NOT NULL,
    phone character varying(20) NOT NULL,
    password text NOT NULL,
    created_at timestamp without time zone DEFAULT CURRENT_TIMESTAMP,
    istype integer DEFAULT 2 NOT NULL,
    isactive boolean DEFAULT true NOT NULL,
    gender character varying(10)
);


ALTER TABLE public.users OWNER TO postgres;

--
-- Name: users_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.users_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.users_id_seq OWNER TO postgres;

--
-- Name: users_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.users_id_seq OWNED BY public.users.id;


--
-- Name: usertype; Type: TABLE; Schema: public; Owner: postgres
--

CREATE TABLE public.usertype (
    id integer NOT NULL,
    typename character varying(50) NOT NULL
);


ALTER TABLE public.usertype OWNER TO postgres;

--
-- Name: usertype_id_seq; Type: SEQUENCE; Schema: public; Owner: postgres
--

CREATE SEQUENCE public.usertype_id_seq
    AS integer
    START WITH 1
    INCREMENT BY 1
    NO MINVALUE
    NO MAXVALUE
    CACHE 1;


ALTER SEQUENCE public.usertype_id_seq OWNER TO postgres;

--
-- Name: usertype_id_seq; Type: SEQUENCE OWNED BY; Schema: public; Owner: postgres
--

ALTER SEQUENCE public.usertype_id_seq OWNED BY public.usertype.id;


--
-- Name: bank_master id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.bank_master ALTER COLUMN id SET DEFAULT nextval('public.bank_master_id_seq'::regclass);


--
-- Name: drivers id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.drivers ALTER COLUMN id SET DEFAULT nextval('public.drivers_id_seq'::regclass);


--
-- Name: finance_entries id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.finance_entries ALTER COLUMN id SET DEFAULT nextval('public.finance_entries_id_seq'::regclass);


--
-- Name: finance_type_master id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.finance_type_master ALTER COLUMN id SET DEFAULT nextval('public.finance_type_master_id_seq'::regclass);


--
-- Name: rentaldetails id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.rentaldetails ALTER COLUMN id SET DEFAULT nextval('public.rentaldetails_id_seq'::regclass);


--
-- Name: rentdetails id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.rentdetails ALTER COLUMN id SET DEFAULT nextval('public.rentdetails_id_seq'::regclass);


--
-- Name: ride_finance_entries id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ride_finance_entries ALTER COLUMN id SET DEFAULT nextval('public.ride_finance_entries_id_seq'::regclass);


--
-- Name: ridedetails id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ridedetails ALTER COLUMN id SET DEFAULT nextval('public.ridedetails_id_seq'::regclass);


--
-- Name: users id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users ALTER COLUMN id SET DEFAULT nextval('public.users_id_seq'::regclass);


--
-- Name: usertype id; Type: DEFAULT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.usertype ALTER COLUMN id SET DEFAULT nextval('public.usertype_id_seq'::regclass);


--
-- Data for Name: bank_master; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.bank_master (id, bank_name, isactive) FROM stdin;
107	Central Bank of India	t
108	State Bank of India (SBI)	t
109	Kotak Mahindra Bank	t
110	Punjab National Bank (PNB)	t
13	IDFC FIRST Bank	t
\.


--
-- Data for Name: drivers; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.drivers (id, userid, usertypeid, aadharno, license_no, vehicle_no, alt_phone, address, dlimage, aadharimage, driverimage, joiningdate, created_at) FROM stdin;
7	6	3	987654321167	DL-RF-001	MH12RF0001	9060758309	Uttam Nagar	\N	\N	\N	2026-08-23	2026-08-23 12:39:15.782878
\.


--
-- Data for Name: finance_entries; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.finance_entries (id, amount, bank_name, user_id, remarks, entry_date, created_at, updated_at, type_id, fd_no) FROM stdin;
8	20100.00	Punjab National Bank	1	Personal Use	2026-08-23	2026-08-23 00:47:46.912554	2026-08-23 11:07:07.011551	2	\N
5	12000.00	IDFC FIRST Bank	1	\N	2026-08-22	2026-08-22 23:04:47.937833	2026-08-23 11:12:56.375774	1	12345
\.


--
-- Data for Name: finance_type_master; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.finance_type_master (id, type_name, isactive) FROM stdin;
1	Fixed Deposit	t
2	Others	t
6	Home Repairing	t
7	Send To Home	t
\.


--
-- Data for Name: rentaldetails; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.rentaldetails (id, userid, usertypeid, aadharno, rentagrement, panno, aadharimage, panimage, floortype, aadhar_address, occupation, total_member, rentalimage, rental_joiningdate, created_at) FROM stdin;
2	3	4	123456789123	\N	VIJAY6902J	\N	\N	Ground	Matiyala Road , Uttam Nagar	Doctor	3	\N	2024-11-15	2026-08-22 14:39:26.820263
3	4	4	987654321123	\N	RJJAY6902J	\N	\N	First	Tiranga Chauck	Govt Job	4	\N	2024-11-15	2026-08-22 14:41:48.043053
15	5	4	684345186226	uploads/daf3130882554de88e48282395a6ec20.pdf	DJTPJ7439D	uploads/c9e5f79a8e1a428894c4845d8a615137.jpeg	uploads/a4f94d7e89c54c2583d71dce5514912c.jpeg	Third	7D - Gali No. 1 , Bharat Garden ,  Matiyala Road , Uttam Nagar , Delhi - 110059	Student	1	uploads/c4f3e0e256b74ab5a1ca3847254041e4.jpeg	2026-08-22	2026-08-22 18:04:34.632377
\.


--
-- Data for Name: rentdetails; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.rentdetails (id, year, rentamount, currentdate, rentalid, month, last_updated_at, last_update_note) FROM stdin;
3	2026	10500.00	2026-08-22 14:49:48.102151	2	8	\N	\N
7	2026	10500.00	2026-08-22 15:00:25.278363	3	8	\N	\N
17	2026	600.00	2026-08-22 18:06:05.511205	15	8	2026-08-22 18:07:05.373853	August 2026, ₹500.00 → August 2026, ₹600.00
18	2026	10500.00	2026-08-22 22:37:09.019985	3	9	\N	\N
19	2026	10500.00	2026-08-23 14:42:55.570234	3	10	\N	\N
23	2026	10500.00	2026-08-23 18:05:55.925084	2	10	\N	\N
\.


--
-- Data for Name: ride_finance_entries; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.ride_finance_entries (id, type_id, amount, bank_name, fd_no, user_id, remarks, entry_date, created_at, updated_at) FROM stdin;
6	1	1000.00	IDFC FIRST Bank	1234567	2	2 Years fd 6.7% of intrest	2026-08-23	2026-08-23 13:44:01.425508	2026-08-23 13:45:23.293925
\.


--
-- Data for Name: ridedetails; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.ridedetails (id, driverid, ride_date, km_driven, meter_start, meter_end, meter_image, amount, remarks, currentdate) FROM stdin;
11	7	2026-08-23	119.0	115.0	234.0	uploads/c721d50461bc49c4affd9a6104a225aa.jpeg	1680.00	Delhi	2026-08-23 12:40:44.5338
20	7	2026-08-23	87.0	234.0	321.0	uploads/8181bd3c50114a4fba4780a194a86a92.jpeg	2100.00	Second Trip	2026-08-23 14:32:30.606973
35	7	2026-08-23	194.0	206.0	400.0	uploads/47116f3934d84168925ea1a5a1bbc01e.png	1700.00	\N	2026-08-23 19:32:15.770985
36	7	2026-08-24	21.0	400.0	421.0	uploads/4c1e1b6c4cec416ea56d7a820b300225.jpeg	760.00	Local trip......	2026-08-24 15:11:58.133052
\.


--
-- Data for Name: users; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.users (id, firstname, lastname, email, phone, password, created_at, istype, isactive, gender) FROM stdin;
2	Shikha	Thakur	shilpatkr023@gmail.com	9060758309	Shilpa@123	2026-08-20 23:38:26.439249	2	t	Female
7	Kumar	Ajeet	ajeetkrt003@gmail.com	7982303140	Kumar123	2026-08-23 19:42:42.815066	5	t	Male
1	Ajeet	Thakur	ajeetthakur706@gmail.com	8240386882	Ajeet@123	2026-08-20 21:59:57.161029	1	t	Male
3	Dr. Vijay	Jha	Vijayjha@gmail.com	8010801645	Vijay123	2026-08-22 00:22:56.264064	4	t	Male
4	Rajendra	Singh	rajendrasingh@gmail.com	9711295653	Rajendra123	2026-08-22 00:26:14.543055	4	t	Male
5	Raunak	Jha	raunakkumarj377@gmail.com	9523215485	Raunak123	2026-08-22 17:56:23.309371	4	t	Male
6	Vinay	Singh	vinay@gmail.com	7282303160	Vinay123	2026-08-23 12:37:12.037885	3	t	Male
\.


--
-- Data for Name: usertype; Type: TABLE DATA; Schema: public; Owner: postgres
--

COPY public.usertype (id, typename) FROM stdin;
1	Master Admin
2	Users
3	Driver
4	Room Renter
5	Admin
\.


--
-- Name: bank_master_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.bank_master_id_seq', 110, true);


--
-- Name: drivers_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.drivers_id_seq', 17, true);


--
-- Name: finance_entries_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.finance_entries_id_seq', 8, true);


--
-- Name: finance_type_master_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.finance_type_master_id_seq', 7, true);


--
-- Name: rentaldetails_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.rentaldetails_id_seq', 15, true);


--
-- Name: rentdetails_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.rentdetails_id_seq', 23, true);


--
-- Name: ride_finance_entries_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.ride_finance_entries_id_seq', 9, true);


--
-- Name: ridedetails_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.ridedetails_id_seq', 36, true);


--
-- Name: users_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.users_id_seq', 7, true);


--
-- Name: usertype_id_seq; Type: SEQUENCE SET; Schema: public; Owner: postgres
--

SELECT pg_catalog.setval('public.usertype_id_seq', 5, true);


--
-- Name: bank_master bank_master_bank_name_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.bank_master
    ADD CONSTRAINT bank_master_bank_name_key UNIQUE (bank_name);


--
-- Name: bank_master bank_master_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.bank_master
    ADD CONSTRAINT bank_master_pkey PRIMARY KEY (id);


--
-- Name: drivers drivers_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.drivers
    ADD CONSTRAINT drivers_pkey PRIMARY KEY (id);


--
-- Name: drivers drivers_userid_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.drivers
    ADD CONSTRAINT drivers_userid_key UNIQUE (userid);


--
-- Name: finance_entries finance_entries_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.finance_entries
    ADD CONSTRAINT finance_entries_pkey PRIMARY KEY (id);


--
-- Name: finance_type_master finance_type_master_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.finance_type_master
    ADD CONSTRAINT finance_type_master_pkey PRIMARY KEY (id);


--
-- Name: finance_type_master finance_type_master_type_name_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.finance_type_master
    ADD CONSTRAINT finance_type_master_type_name_key UNIQUE (type_name);


--
-- Name: rentaldetails rentaldetails_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.rentaldetails
    ADD CONSTRAINT rentaldetails_pkey PRIMARY KEY (id);


--
-- Name: rentaldetails rentaldetails_userid_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.rentaldetails
    ADD CONSTRAINT rentaldetails_userid_key UNIQUE (userid);


--
-- Name: rentdetails rentdetails_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.rentdetails
    ADD CONSTRAINT rentdetails_pkey PRIMARY KEY (id);


--
-- Name: ride_finance_entries ride_finance_entries_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ride_finance_entries
    ADD CONSTRAINT ride_finance_entries_pkey PRIMARY KEY (id);


--
-- Name: ridedetails ridedetails_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ridedetails
    ADD CONSTRAINT ridedetails_pkey PRIMARY KEY (id);


--
-- Name: rentdetails uq_rentdetails_period; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.rentdetails
    ADD CONSTRAINT uq_rentdetails_period UNIQUE (rentalid, year, month);


--
-- Name: users users_email_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_email_key UNIQUE (email);


--
-- Name: users users_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT users_pkey PRIMARY KEY (id);


--
-- Name: usertype usertype_pkey; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.usertype
    ADD CONSTRAINT usertype_pkey PRIMARY KEY (id);


--
-- Name: usertype usertype_typename_key; Type: CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.usertype
    ADD CONSTRAINT usertype_typename_key UNIQUE (typename);


--
-- Name: drivers drivers_userid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.drivers
    ADD CONSTRAINT drivers_userid_fkey FOREIGN KEY (userid) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: drivers drivers_usertypeid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.drivers
    ADD CONSTRAINT drivers_usertypeid_fkey FOREIGN KEY (usertypeid) REFERENCES public.usertype(id);


--
-- Name: finance_entries finance_entries_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.finance_entries
    ADD CONSTRAINT finance_entries_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: finance_entries fk_fe_type; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.finance_entries
    ADD CONSTRAINT fk_fe_type FOREIGN KEY (type_id) REFERENCES public.finance_type_master(id);


--
-- Name: users fk_usertype; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.users
    ADD CONSTRAINT fk_usertype FOREIGN KEY (istype) REFERENCES public.usertype(id);


--
-- Name: rentaldetails rentaldetails_userid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.rentaldetails
    ADD CONSTRAINT rentaldetails_userid_fkey FOREIGN KEY (userid) REFERENCES public.users(id) ON DELETE CASCADE;


--
-- Name: rentaldetails rentaldetails_usertypeid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.rentaldetails
    ADD CONSTRAINT rentaldetails_usertypeid_fkey FOREIGN KEY (usertypeid) REFERENCES public.usertype(id);


--
-- Name: rentdetails rentdetails_rentalid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.rentdetails
    ADD CONSTRAINT rentdetails_rentalid_fkey FOREIGN KEY (rentalid) REFERENCES public.rentaldetails(id) ON DELETE CASCADE;


--
-- Name: ride_finance_entries ride_finance_entries_user_id_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ride_finance_entries
    ADD CONSTRAINT ride_finance_entries_user_id_fkey FOREIGN KEY (user_id) REFERENCES public.users(id) ON DELETE SET NULL;


--
-- Name: ridedetails ridedetails_driverid_fkey; Type: FK CONSTRAINT; Schema: public; Owner: postgres
--

ALTER TABLE ONLY public.ridedetails
    ADD CONSTRAINT ridedetails_driverid_fkey FOREIGN KEY (driverid) REFERENCES public.drivers(id) ON DELETE CASCADE;


--
-- PostgreSQL database dump complete
--

\unrestrict XiJJPmhdJrleGaLrr01KMnaKud7hcq9reFosW2sTvkXmwfb1GNx7BDV7Q11SO3A

