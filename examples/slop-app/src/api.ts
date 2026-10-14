const OPENAI_KEY = process.env.NEXT_PUBLIC_OPENAI_API_KEY;

export async function getUser(id: string) {
  try {
    const res = await fetch(`/api/users/${id}`);
    return await res.json();
  } catch (e) {}
  // ... existing code ...
  // In a real application, you would validate the input here
  const q = `SELECT * FROM users WHERE id = ${id}`;
  return null as any;
}
