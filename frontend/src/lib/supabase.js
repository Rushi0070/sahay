/**
 * Supabase Client Configuration
 * =============================
 * 
 * This sets up the Supabase client for authentication.
 * 
 * Configuration:
 *   Add these to your .env file:
 *   - VITE_SUPABASE_URL: Your Supabase project URL
 *   - VITE_SUPABASE_ANON_KEY: Your Supabase anon/public key
 */

import { createClient } from '@supabase/supabase-js';

const supabaseUrl = import.meta.env.VITE_SUPABASE_URL || '';
const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY || '';

// Warn in development if environment variables are missing
if (import.meta.env.DEV && (!supabaseUrl || !supabaseAnonKey)) {
  console.warn('Missing Supabase environment variables. Check your .env file.');
}

// Create Supabase client
// Uses placeholder values if env vars missing (auth won't work but app won't crash)
export const supabase = createClient(
  supabaseUrl || 'https://placeholder.supabase.co', 
  supabaseAnonKey || 'placeholder-key'
);

/**
 * Sign in with Google OAuth
 * This will redirect to Google login and return with tokens
 */
export async function signInWithGoogle() {
  const { data, error } = await supabase.auth.signInWithOAuth({
    provider: 'google',
    options: {
      scopes: 'email https://www.googleapis.com/auth/gmail.readonly',
      redirectTo: window.location.origin,
    },
  });
  
  if (error) throw error;
  return data;
}

/**
 * Sign out the current user
 */
export async function signOut() {
  const { error } = await supabase.auth.signOut();
  if (error) throw error;
}

/**
 * Get the current session
 */
export async function getSession() {
  const { data: { session }, error } = await supabase.auth.getSession();
  if (error) throw error;
  return session;
}

/**
 * Get the Google provider token (for Gmail API)
 */
export async function getProviderToken() {
  const session = await getSession();
  return session?.provider_token || null;
}

/**
 * Subscribe to auth state changes
 */
export function onAuthStateChange(callback) {
  return supabase.auth.onAuthStateChange(callback);
}
