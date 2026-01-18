/**
 * SyncApply - Main Application Component
 * =======================================
 * 
 * This is the main entry point for the React application.
 * It handles:
 *   - Authentication state management
 *   - Routing between landing page and dashboard
 *   - UI components (navbar, hero, etc.)
 * 
 * The Dashboard component is lazy-loaded for better initial page load performance.
 */

import React, { useState, useEffect, useRef, lazy, Suspense } from 'react';
import { motion, useScroll, useTransform, useSpring, useMotionValue } from 'framer-motion';
import { 
  Mail, 
  Zap, 
  ArrowRight, 
  Github, 
  Lock,
  Target,
  Loader2,
  LogOut
} from 'lucide-react';
import { signInWithGoogle, signOut, getSession, onAuthStateChange } from './lib/supabase';

// Lazy load Dashboard component for better initial page load performance
// This means the Dashboard code is only downloaded when a user logs in
const Dashboard = lazy(() => import('./Dashboard'));


// =============================================================================
// AUTH HOOK
// =============================================================================

function useAuth() {
  const [user, setUser] = useState(null);
  const [providerToken, setProviderToken] = useState(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Get initial session
    getSession().then((session) => {
      setUser(session?.user ?? null);
      setProviderToken(session?.provider_token ?? null);
      setLoading(false);
    }).catch((error) => {
      console.error('Error getting session:', error);
      setLoading(false);
    });

    // Listen for auth changes
    const { data: { subscription } } = onAuthStateChange((event, session) => {
      setUser(session?.user ?? null);
      setProviderToken(session?.provider_token ?? null);
      setLoading(false);
    });

    return () => subscription.unsubscribe();
  }, []);

  return { user, providerToken, loading };
}


// =============================================================================
// CUSTOM CURSOR
// =============================================================================

const CustomCursor = () => {
  const cursorX = useMotionValue(-100);
  const cursorY = useMotionValue(-100);
  const [isHovered, setIsHovered] = useState(false);

  const springConfig = { damping: 25, stiffness: 300, mass: 0.5 };
  const smoothX = useSpring(cursorX, springConfig);
  const smoothY = useSpring(cursorY, springConfig);

  useEffect(() => {
    const moveCursor = (e) => {
      cursorX.set(e.clientX);
      cursorY.set(e.clientY);
    };

    const handleHover = (e) => {
      const target = e.target;
      const isInteractive = target.closest('button, a, input, .interactive');
      setIsHovered(!!isInteractive);
    };

    window.addEventListener('mousemove', moveCursor);
    window.addEventListener('mouseover', handleHover);
    return () => {
      window.removeEventListener('mousemove', moveCursor);
      window.removeEventListener('mouseover', handleHover);
    };
  }, [cursorX, cursorY]);

  return (
    <motion.div
      className="fixed top-0 left-0 w-8 h-8 pointer-events-none z-[999] mix-blend-difference hidden md:block"
      style={{
        x: smoothX,
        y: smoothY,
        translateX: "-50%",
        translateY: "-50%",
      }}
    >
      <motion.div
        animate={{
          scale: isHovered ? 2.5 : 1,
          backgroundColor: isHovered ? "white" : "white",
        }}
        className="w-full h-full rounded-full border border-white/50"
      />
    </motion.div>
  );
};


// =============================================================================
// BACKGROUND COMPONENTS
// =============================================================================

const GrainOverlay = () => (
  <div className="fixed inset-0 pointer-events-none z-[100] opacity-[0.03] mix-blend-overlay">
    <svg viewBox="0 0 200 200" xmlns="http://www.w3.org/2000/svg">
      <filter id="noiseFilter">
        <feTurbulence type="fractalNoise" baseFrequency="0.65" numOctaves="3" stitchTiles="stitch" />
      </filter>
      <rect width="100%" height="100%" filter="url(#noiseFilter)" />
    </svg>
  </div>
);

const FluidAmbient = () => (
  <div className="fixed inset-0 z-0 bg-[#000]">
    <div className="absolute top-[-10%] left-[-10%] w-[50%] h-[50%] rounded-full bg-indigo-600/20 blur-[120px] animate-pulse" />
    <div className="absolute bottom-[-10%] right-[-10%] w-[50%] h-[50%] rounded-full bg-cyan-600/10 blur-[120px]" />
    <div className="absolute inset-0 opacity-[0.1]" style={{ backgroundImage: 'linear-gradient(#ffffff 1px, transparent 1px), linear-gradient(90deg, #ffffff 1px, transparent 1px)', backgroundSize: '60px 60px' }} />
  </div>
);

const ScrollProgressBar = () => {
  const { scrollYProgress } = useScroll();
  const scaleX = useSpring(scrollYProgress, {
    stiffness: 100,
    damping: 30,
    restDelta: 0.001
  });

  return (
    <motion.div 
      className="fixed top-0 left-0 right-0 h-[2px] bg-indigo-500 origin-left z-[1000]"
      style={{ scaleX }}
    />
  );
};


// =============================================================================
// UI COMPONENTS
// =============================================================================

const PerspectiveCard = ({ children, className = "" }) => {
  const x = useMotionValue(0);
  const y = useMotionValue(0);

  const mouseXSpring = useSpring(x);
  const mouseYSpring = useSpring(y);

  const rotateX = useTransform(mouseYSpring, [-0.5, 0.5], ["10deg", "-10deg"]);
  const rotateY = useTransform(mouseXSpring, [-0.5, 0.5], ["-10deg", "10deg"]);

  const handleMouseMove = (e) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const width = rect.width;
    const height = rect.height;
    const mouseX = e.clientX - rect.left;
    const mouseY = e.clientY - rect.top;
    const xPct = mouseX / width - 0.5;
    const yPct = mouseY / height - 0.5;
    x.set(xPct);
    y.set(yPct);
  };

  const handleMouseLeave = () => {
    x.set(0);
    y.set(0);
  };

  return (
    <motion.div
      onMouseMove={handleMouseMove}
      onMouseLeave={handleMouseLeave}
      style={{
        rotateY,
        rotateX,
        transformStyle: "preserve-3d",
      }}
      className={`relative ${className}`}
    >
      <div style={{ transform: "translateZ(50px)" }} className="h-full w-full">
        {children}
      </div>
    </motion.div>
  );
};

const MagneticButton = ({ children, className = "", onClick, disabled = false }) => {
  const [position, setPosition] = useState({ x: 0, y: 0 });
  const ref = useRef(null);

  const handleMouse = (e) => {
    if (disabled) return;
    const { clientX, clientY } = e;
    const { height, width, left, top } = ref.current.getBoundingClientRect();
    const middleX = clientX - (left + width / 2);
    const middleY = clientY - (top + height / 2);
    setPosition({ x: middleX * 0.3, y: middleY * 0.3 });
  };

  const reset = () => setPosition({ x: 0, y: 0 });

  return (
    <motion.button
      ref={ref}
      onClick={onClick}
      disabled={disabled}
      onMouseMove={handleMouse}
      onMouseLeave={reset}
      animate={{ x: position.x, y: position.y }}
      transition={{ type: "spring", stiffness: 150, damping: 15, mass: 0.1 }}
      className={`relative ${className} ${disabled ? 'opacity-50 cursor-not-allowed' : ''}`}
    >
      {children}
    </motion.button>
  );
};


// =============================================================================
// LOADING FALLBACK
// =============================================================================

const LoadingSpinner = () => (
  <div className="h-screen flex items-center justify-center">
    <Loader2 className="w-12 h-12 text-indigo-500 animate-spin" />
  </div>
);


// =============================================================================
// NAVBAR
// =============================================================================

const Navbar = ({ user, onSignOut }) => {
  return (
    <nav className="fixed top-0 w-full z-50 px-8 py-6 flex justify-between items-center">
      <div className="flex items-center gap-3">
        <div className="w-10 h-10 bg-white flex items-center justify-center rounded-full">
          <Zap className="text-black w-6 h-6 fill-current" />
        </div>
        <span className="text-xl font-black tracking-tighter text-white uppercase">Sync.</span>
      </div>

      {!user && (
        <div className="hidden md:flex items-center gap-1 bg-white/5 backdrop-blur-xl border border-white/10 rounded-full px-2 py-1">
          {['Features', 'Security', 'Pricing'].map((item) => (
            <button key={item} className="px-5 py-2 text-xs font-bold text-gray-400 hover:text-white transition-all uppercase tracking-widest">
              {item}
            </button>
          ))}
        </div>
      )}

      {user ? (
        <div className="flex items-center gap-4">
          <span className="text-sm text-gray-400 hidden md:block">{user.email}</span>
          <MagneticButton 
            onClick={onSignOut}
            className="bg-white/10 text-white px-6 py-3 rounded-full text-xs font-black uppercase tracking-widest hover:bg-white/20 transition-colors flex items-center gap-2"
          >
            <LogOut className="w-4 h-4" /> Sign Out
          </MagneticButton>
        </div>
      ) : (
        <MagneticButton className="bg-white text-black px-6 py-3 rounded-full text-xs font-black uppercase tracking-widest hover:scale-105 transition-transform">
          Start Trial
        </MagneticButton>
      )}
    </nav>
  );
};


// =============================================================================
// HERO SECTION
// =============================================================================

const Hero = ({ onGoogleSignIn, loading }) => {
  const { scrollYProgress } = useScroll();
  const y = useTransform(scrollYProgress, [0, 0.5], [0, -100]);
  const opacity = useTransform(scrollYProgress, [0, 0.2], [1, 0]);

  return (
    <section className="relative h-screen flex flex-col items-center justify-center px-6 overflow-hidden">
      <motion.div style={{ y, opacity }} className="relative z-10 text-center w-full max-w-4xl">
        <motion.div 
          initial={{ opacity: 0, scale: 0.9 }}
          animate={{ opacity: 1, scale: 1 }}
          className="mb-8 inline-block px-4 py-2 border border-white/10 rounded-full bg-white/5 backdrop-blur-sm"
        >
          <span className="text-[10px] font-black uppercase tracking-[0.3em] text-indigo-400 flex items-center gap-2">
            <Target className="w-3 h-3" /> Precision Hiring OS
          </span>
        </motion.div>

        <motion.h1 
          className="text-[12vw] md:text-[9vw] font-black text-white leading-[0.8] tracking-tighter mb-10 uppercase"
        >
          <motion.span 
            initial={{ y: 120, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ duration: 1, ease: [0.16, 1, 0.3, 1] }}
            className="block"
          >
            Hunt Smarter.
          </motion.span>
          <motion.span 
            initial={{ y: 120, opacity: 0 }}
            animate={{ y: 0, opacity: 1 }}
            transition={{ delay: 0.2, duration: 1, ease: [0.16, 1, 0.3, 1] }}
            className="block text-transparent"
            style={{ WebkitTextStroke: '1px rgba(255,255,255,0.6)' }}
          >
            Close Faster.
          </motion.span>
        </motion.h1>

        <motion.p 
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          transition={{ delay: 0.6 }}
          className="max-w-xl mx-auto text-gray-400 text-lg md:text-xl font-medium leading-relaxed mb-12"
        >
          Gmail extraction for the elite 1%. SyncApply automates your application tracking so you can focus on the final signature.
        </motion.p>

        <motion.div 
          initial={{ opacity: 0, y: 20 }}
          animate={{ opacity: 1, y: 0 }}
          transition={{ delay: 0.8 }}
        >
          <MagneticButton 
            onClick={onGoogleSignIn}
            disabled={loading}
            className="group bg-indigo-600 px-10 py-5 rounded-full flex items-center gap-3 text-white font-black uppercase text-sm shadow-2xl shadow-indigo-600/40 mx-auto"
          >
            {loading ? (
              <Loader2 className="w-5 h-5 animate-spin" />
            ) : (
              <>
                <Mail className="w-5 h-5" /> Connect Gmail <ArrowRight className="w-5 h-5 group-hover:translate-x-1 transition-transform" />
              </>
            )}
          </MagneticButton>
        </motion.div>
      </motion.div>

      <motion.div 
        animate={{ y: [0, -20, 0] }}
        transition={{ duration: 5, repeat: Infinity, ease: "easeInOut" }}
        className="absolute top-1/4 left-10 w-48 h-48 border border-white/5 rounded-3xl bg-white/5 backdrop-blur-3xl hidden xl:block"
      />
      <motion.div 
        animate={{ y: [0, 20, 0] }}
        transition={{ duration: 7, repeat: Infinity, ease: "easeInOut" }}
        className="absolute bottom-1/4 right-10 w-64 h-32 border border-white/5 rounded-3xl bg-white/5 backdrop-blur-3xl hidden xl:block"
      />
    </section>
  );
};


// =============================================================================
// LANDING PAGE SECTIONS
// =============================================================================

const BentoGrid = () => {
  return (
    <section className="py-24 px-8 max-w-7xl mx-auto">
      <div className="grid md:grid-cols-12 grid-rows-2 gap-6 h-auto md:h-[800px]">
        <PerspectiveCard className="md:col-span-8 group">
          <div className="h-full bg-white/5 border border-white/10 rounded-[3rem] p-12 relative overflow-hidden transition-colors hover:bg-white/[0.08]">
            <div className="absolute top-0 right-0 p-12 opacity-10 group-hover:opacity-20 transition-opacity">
              <Mail className="w-64 h-64 text-white" />
            </div>
            <div className="relative z-10 h-full flex flex-col justify-end">
              <h3 className="text-4xl font-black text-white mb-4 uppercase tracking-tighter">Intelligent Scraper</h3>
              <p className="text-gray-400 max-w-md">Our neural engine identifies 1,200+ unique job board headers instantly. No data ever leaves your browser unencrypted.</p>
            </div>
          </div>
        </PerspectiveCard>

        <PerspectiveCard className="md:col-span-4">
          <div className="h-full bg-indigo-600 rounded-[3rem] p-12 flex flex-col justify-between">
            <Zap className="text-white w-12 h-12 fill-current" />
            <div>
              <h3 className="text-2xl font-black text-white mb-2 uppercase">100ms Sync</h3>
              <p className="text-indigo-100 text-sm">Real-time status updates as soon as the email hits your primary folder.</p>
            </div>
          </div>
        </PerspectiveCard>

        <PerspectiveCard className="md:col-span-4">
          <div className="h-full bg-[#111] border border-white/10 rounded-[3rem] p-12 flex flex-col justify-between transition-colors hover:border-indigo-500/30">
            <Lock className="text-indigo-500 w-12 h-12" />
            <div>
              <h3 className="text-2xl font-black text-white mb-2 uppercase">Privacy First</h3>
              <p className="text-gray-500 text-sm">We only store metadata. Your email body remains 100% private and unread by us.</p>
            </div>
          </div>
        </PerspectiveCard>

        <PerspectiveCard className="md:col-span-8">
          <div className="h-full bg-white/5 border border-white/10 rounded-[3rem] p-12 flex items-center justify-between overflow-hidden transition-colors hover:bg-white/[0.08]">
            <div className="max-w-xs">
              <h3 className="text-4xl font-black text-white mb-4 uppercase tracking-tighter">Universal Search</h3>
              <p className="text-gray-400">Filter applications by salary, location, or status with sub-second latency.</p>
            </div>
            <div className="hidden lg:block w-64 h-32 bg-indigo-500/20 rounded-2xl border border-indigo-500/40 relative">
              <div className="absolute inset-4 bg-indigo-500/30 rounded flex items-center justify-center font-mono text-indigo-300 text-xs">
                SEARCHING...
              </div>
            </div>
          </div>
        </PerspectiveCard>
      </div>
    </section>
  );
};

const ScrollingText = () => {
  return (
    <div className="py-20 overflow-hidden border-y border-white/5 bg-white/[0.02]">
      <motion.div 
        animate={{ x: [0, -1000] }}
        transition={{ repeat: Infinity, duration: 20, ease: "linear" }}
        className="flex whitespace-nowrap gap-20"
      >
        {[...Array(10)].map((_, i) => (
          <span key={i} className="text-6xl font-black uppercase text-white/5 tracking-tighter italic">
            Automate Everything * Scale Your Search * Focus on Interviews *
          </span>
        ))}
      </motion.div>
    </div>
  );
};

const CTASection = ({ onGoogleSignIn, loading }) => (
  <section className="py-48 px-6 text-center">
    <motion.div 
      whileHover={{ scale: 0.98 }}
      className="max-w-5xl mx-auto bg-white p-24 rounded-[4rem] text-black relative overflow-hidden"
    >
      <div className="absolute top-0 left-0 w-full h-2 bg-indigo-600" />
      <h2 className="text-6xl md:text-8xl font-black tracking-tighter uppercase leading-[0.85] mb-12">
        Land the <br /> dream role.
      </h2>
      <MagneticButton 
        onClick={onGoogleSignIn}
        disabled={loading}
        className="bg-black text-white px-12 py-6 rounded-full font-black uppercase tracking-widest hover:scale-110 transition-transform inline-flex items-center gap-3"
      >
        {loading ? (
          <Loader2 className="w-5 h-5 animate-spin" />
        ) : (
          'Get Early Access'
        )}
      </MagneticButton>
    </motion.div>
  </section>
);

const Footer = () => (
  <footer className="py-20 px-8 border-t border-white/5 bg-black">
    <div className="max-w-7xl mx-auto flex flex-col md:flex-row justify-between items-end gap-12">
      <div className="max-w-md">
        <h2 className="text-6xl font-black text-white mb-8 tracking-tighter uppercase">Ready to <br /> scale?</h2>
        <div className="flex gap-4">
          <Github className="text-gray-600 hover:text-white cursor-pointer transition-colors" />
          <span className="text-gray-600 font-bold uppercase text-xs tracking-widest">Built with Supabase & Framer Motion</span>
        </div>
      </div>
      <div className="text-right">
        <p className="text-gray-500 font-medium mb-2">2026 SyncApply Labs</p>
        <p className="text-gray-700 text-xs uppercase tracking-[0.2em]">Crafted for the elite 1% of candidates.</p>
      </div>
    </div>
  </footer>
);


// =============================================================================
// MAIN APP
// =============================================================================

const App = () => {
  const { user, providerToken, loading: authLoading } = useAuth();
  const [signInLoading, setSignInLoading] = useState(false);

  const handleGoogleSignIn = async () => {
    setSignInLoading(true);
    try {
      await signInWithGoogle();
    } catch (error) {
      console.error('Sign in error:', error);
    } finally {
      setSignInLoading(false);
    }
  };

  const handleSignOut = async () => {
    try {
      await signOut();
    } catch (error) {
      console.error('Sign out error:', error);
    }
  };

  return (
    <div className="bg-[#000] min-h-screen font-sans selection:bg-indigo-500 selection:text-white relative overflow-x-hidden">
      <ScrollProgressBar />
      <CustomCursor />
      <GrainOverlay />
      <FluidAmbient />
      
      <div className="relative z-10">
        <Navbar user={user} onSignOut={handleSignOut} />
        
        <main>
          {authLoading ? (
            // Loading state while checking auth
            <LoadingSpinner />
          ) : user ? (
            // Logged in - show dashboard (lazy loaded with Suspense)
            <Suspense fallback={<LoadingSpinner />}>
              <Dashboard user={user} providerToken={providerToken} />
            </Suspense>
          ) : (
            // Not logged in - show landing page
            <>
              <Hero onGoogleSignIn={handleGoogleSignIn} loading={signInLoading} />
              <ScrollingText />
              
              <section className="py-24 text-center">
                <motion.div
                  initial={{ opacity: 0 }}
                  whileInView={{ opacity: 1 }}
                  viewport={{ once: true }}
                  className="px-6"
                >
                  <h2 className="text-xs font-black uppercase tracking-[0.4em] text-indigo-500 mb-6">The Platform</h2>
                  <p className="text-5xl md:text-7xl font-black text-white tracking-tighter uppercase max-w-5xl mx-auto leading-none">
                    More than a tracker. <br />
                    <span className="text-gray-800">Your career OS.</span>
                  </p>
                </motion.div>
              </section>

              <BentoGrid />
              <CTASection onGoogleSignIn={handleGoogleSignIn} loading={signInLoading} />
            </>
          )}
        </main>

        <Footer />
      </div>
    </div>
  );
};

export default App;
